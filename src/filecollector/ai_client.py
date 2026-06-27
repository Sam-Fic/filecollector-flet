"""AI assistant backend client.

Design goals:
- Pairs with the in-process AI side-panel of the GUI; talks to any
  third-party LLM through an OpenAI-compatible Chat Completions endpoint
  (OpenAI, Azure OpenAI, Microsoft Foundry's Fast Context and other
  specialised models, or any compatible local endpoint).
- Maps function-calling 1:1 to the existing CLI flags. The caller
  (``main_window``) reuses ``filecollector.cli.apply_cli_args`` to run the
  mutations on the engine, so the CLI / IPC / MCP / AI paths all share
  the same mutation semantics.

Notes:
- We deliberately avoid extra dependencies such as ``requests`` and stick
  to the stdlib ``urllib.request``.
- The default is HTTPS; if the user configures an HTTP endpoint they are
  responsible for confirming it is safe on the local network.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


# ---------------------------------------------------------------------------
# OpenAI-compatible function-calling schema
# ---------------------------------------------------------------------------
# One entry per flag supported by ``filecollector.cli``. Descriptions are in
# English so the LLM receives consistent instructions regardless of the
# user's UI language.
TOOL_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "set_work_dir",
            "description": (
                "Switch the working directory. This clears the current "
                "orchestration list and refreshes the file tree."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path of the new working directory.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_files",
            "description": (
                "Add one or more files to the orchestration list. Paths must "
                "be absolute. Only files are added — directories are skipped."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Array of absolute file paths.",
                    },
                },
                "required": ["paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_text",
            "description": (
                "Insert a custom text block into the orchestration list "
                "(e.g. a task description, a guiding prompt, or a question). "
                "By default the block is appended; pass `position` to insert "
                "at a specific 0-based index instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text content to insert.",
                    },
                    "position": {
                        "type": "integer",
                        "description": (
                            "Optional 0-based insertion index. Omit to append "
                            "to the end of the list."
                        ),
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_item",
            "description": (
                "Delete an item from the orchestration list by its "
                "0-based index."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "0-based index of the item to delete.",
                    },
                },
                "required": ["index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_item",
            "description": (
                "Move an item in the orchestration list from one 0-based "
                "index to another."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_index": {
                        "type": "integer",
                        "description": "Source index.",
                    },
                    "to_index": {
                        "type": "integer",
                        "description": "Destination index.",
                    },
                },
                "required": ["from_index", "to_index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_items",
            "description": (
                "Empty the entire orchestration list. Does not modify the "
                "working directory."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_use_absolute",
            "description": (
                "Toggle path mode: True = export absolute paths, "
                "False = export paths relative to the working directory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "boolean",
                        "description": "True to use absolute paths.",
                    },
                },
                "required": ["value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_show_header",
            "description": "Whether to prepend the work-directory header to exported files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"type": "boolean", "description": "True to enable the header"},
                },
                "required": ["value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List files under a directory (defaults to the current work directory). "
                "Supports an optional case-insensitive glob pattern (e.g. '*ai*.py' or 'README*') "
                "and an optional max_depth to limit recursion (default 8). Hidden files and "
                "common build/VCS directories are skipped. Returns up to `max_results` paths "
                "(default 200). Use this whenever the user gives a vague instruction like "
                "'add all files about X' or 'find anything related to Y' — explore first, "
                "then call add_files with the chosen absolute paths in batches. "
                "NOTE: a list result is a CANDIDATE set, not a final answer. Filenames alone "
                "are often misleading; the only reliable way to confirm relevance is to "
                "read_file each candidate's first ~20-40 lines (or its module-level docstring / "
                "config schema) before adding. When a file's name is ambiguous or several "
                "candidates share similar names, you MUST call read_file — never judge by name alone."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Optional case-insensitive glob matched against the file name "
                            "(not the full path). Examples: '*ai*', '*.md', 'README*'."
                        ),
                    },
                    "directory": {
                        "type": "string",
                        "description": (
                            "Absolute directory to scan. Defaults to the current work directory."
                        ),
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum recursion depth. Defaults to 8.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of paths to return. Defaults to 200.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the text content of a file (with a 1-based line-numbered view). "
                "Use this to inspect a file's contents — for example to verify what a "
                "config or source file actually contains before deciding whether to add it. "
                "Binary files (containing NUL bytes) are detected and rejected with a clear "
                "message. For large files, content is truncated to `max_bytes` (default "
                "100KB, hard cap 512KB) and `max_lines` (default 500). Use `start_line` "
                "(1-based) and `max_lines` to read a specific region in chunks. "
                "TYPICAL USE: after list_files, call read_file with max_lines=30-50 to peek "
                "at the top of each candidate (docstring / imports / class names) so you "
                "don't add the wrong file based on its name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file to read.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "1-based line number to start reading from. Defaults to 1.",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Maximum number of lines to return. Defaults to 500, hard cap 2000.",
                    },
                    "max_bytes": {
                        "type": "integer",
                        "description": "Maximum total bytes to return. Defaults to 102400 (100KB), hard cap 524288 (512KB).",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_items",
            "description": (
                "Inspect the current orchestration list (the items the user will export). "
                "Returns a numbered view of all items — both file entries (with their "
                "absolute path) and text blocks (with a content preview). Use this to "
                "verify the result of add_files / add_text / move_item / remove_item "
                "before reporting back to the user. If `kind` is provided, only that "
                "type is shown: 'file' or 'text'. Truncated to `max_items` (default 100)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "description": "Optional filter: 'file' or 'text'. Omit to show everything.",
                    },
                    "max_items": {
                        "type": "integer",
                        "description": "Maximum number of items to return. Defaults to 100, hard cap 500.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_git_status",
            "description": (
                "Get the current Git working tree status (modified, added, untracked files). "
                "Use this to understand what the user is currently working on before selecting files."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_git_diff",
            "description": (
                "Get the Git diff of the working tree or staged area. "
                "Use this to read the exact code changes and decide which files are relevant to the context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "staged": {
                        "type": "boolean",
                        "description": (
                            "Whether to get the staged diff (true) or unstaged working tree diff (false). "
                            "Default is false."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_git_log",
            "description": (
                "List recent Git commits. Use this to find a specific historical change."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_count": {
                        "type": "integer",
                        "description": "Maximum number of commits to return. Default 10, max 50.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_git_commit_diff",
            "description": (
                "Get the diff of a specific Git commit by its hash."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "commit_hash": {
                        "type": "string",
                        "description": "The hash of the commit to inspect.",
                    },
                },
                "required": ["commit_hash"],
            },
        },
    },
]


def build_system_prompt(work_dir: str | None, items: list[dict], use_absolute: bool, show_header: bool) -> str:
    """Build the English system prompt from the current engine state."""
    work_dir_str = work_dir or "(not set)"
    file_count = sum(1 for it in items if it.get("type") == "file")
    text_count = sum(1 for it in items if it.get("type") == "text")
    mode = "absolute" if use_absolute else "relative"
    header = "on" if show_header else "off"

    if items:
        lines = []
        for idx, it in enumerate(items):
            t = it.get("type")
            if t == "file":
                p = it.get("path", "")
                name = os.path.basename(p) or p
                tag = "abs" if it.get("force_absolute") else "rel"
                lines.append(f"  [{idx}] file({tag}): {name}")
            else:
                preview = (it.get("content") or "")[:40].replace("\n", " ")
                if len(it.get("content") or "") > 40:
                    preview += "…"
                lines.append(f"  [{idx}] text: {preview}")
        item_block = "\n".join(lines)
    else:
        item_block = "  (empty)"

    return (
        "You are the AI assistant for FileCollector, a file-collecting and "
        "orchestration tool. The user picks files in a working directory; you "
        "understand their intent and use the provided tools to manipulate the "
        "orchestration list.\n\n"
        f"Current state:\n"
        f"- Work directory: {work_dir_str}\n"
        f"- Orchestration list: {len(items)} item(s) ({file_count} file(s), {text_count} text block(s))\n"
        f"- Path mode: {mode}\n"
        f"- Header info: {header}\n"
        f"- List contents:\n{item_block}\n\n"
        "Available tools:\n"
        "- set_work_dir(path): switch the working directory (clears the list)\n"
        "- list_files(pattern?, directory?, max_depth?, max_results?): scan a directory for files; "
        "pattern is a case-insensitive glob on the file name. Use this to explore before adding.\n"
        "- read_file(path, start_line?, max_lines?, max_bytes?): read a file's text content "
        "with 1-based line numbers. Use to inspect a file before deciding whether to add it, "
        "or to look up specific information (config values, doc strings, etc.). Binary files are rejected.\n"
        "- list_items(kind?, max_items?): inspect the current orchestration list; "
        "kind='file' or 'text' to filter. Always call this after add_files / add_text / "
        "move_item / remove_item to verify the result before telling the user what was done.\n"
        "- add_files(paths): add files (absolute paths required; missing files are skipped)\n"
        "- add_text(text, position?): insert a text block (appends if position is omitted)\n"
        "- remove_item(index): delete an item by 0-based index\n"
        "- move_item(from_index, to_index): move an item\n"
        "- clear_items(): empty the orchestration list\n"
        "- set_use_absolute(value): toggle absolute/relative path mode\n"
        "- set_show_header(value): toggle writing the work-directory header in exports\n"
        "- get_git_status(): check what files are modified/untracked in the working tree.\n"
        "- get_git_diff(staged?): read the exact code changes to understand the user's current task.\n"
        "- get_git_log(max_count?): list recent commits to find historical context.\n"
        "- get_git_commit_diff(commit_hash): inspect the code changes of a specific past commit.\n\n"
        "Workflow rules:\n"
        "1. Prefer tool calls over asking the user for paths you can discover yourself. "
        "If the user says 'add all files about X' or 'find files matching Y', call "
        "list_files first with a sensible pattern (e.g. '*x*'), inspect the results, "
        "then call add_files with the chosen absolute paths in batches.\n"
        "2. NEVER add a file based on its name alone. After list_files, the result is a "
        "CANDIDATE set. For each candidate you intend to add (or when in doubt), call "
        "read_file with max_lines≈30-50 to peek at the top of the file — module docstring, "
        "imports, class/function names, config schema — to confirm it really matches the "
        "user's intent. Skip this only for very short, unambiguous files (e.g. a single "
        "README.md whose first line clearly states the topic).\n"
        "3. Pass absolute paths to add_files. The server decides how to store them: files "
        "inside the current work directory are stored as relative paths and reflected as "
        "checked items in the file tree; files outside the work directory are stored as "
        "absolute paths and will not appear in the file tree.\n"
        "4. The UI refreshes in real time after each tool call, so the user can see results immediately.\n"
        "5. After any mutation (add_files / add_text / move_item / remove_item / clear_items), "
        "call list_items to confirm what actually landed in the list before reporting to the user. "
        "If something is missing or wrong, fix it in the same turn — don't assume success.\n"
        "6. Be concise and professional. Reply in the same language the user uses. "
        "When no tool call is needed, just explain in natural language.\n"
        "7. When the user asks to 'collect files for my current PR' or 'gather context for "
        "the bug I just fixed', ALWAYS call `get_git_status` and `get_git_diff` first. "
        "Analyze the diff to identify ALL related files (including headers, configs, or "
        "test files that might not show up in the diff but are relevant), then use "
        "`add_files` to collect them."
    )


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------
class AIClientError(Exception):
    """Raised by :class:`AIClient` for any failure the user should see.

    The accompanying message is a user-facing string (currently Chinese)
    that is rendered directly in the chat panel.
    """


class AIClient:
    """Lightweight OpenAI-compatible Chat Completions client.

    Works with any compatible endpoint: OpenAI, Azure OpenAI via the
    ``base_url`` + ``api_key`` pattern, a local Ollama server exposing
    ``/v1``, Microsoft Foundry's Fast Context, etc.
    """

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = float(timeout)

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Send a single chat request and return the raw JSON dict."""
        if not self.base_url:
            raise AIClientError("API 基础地址未配置, 请在 设置 → AI 设置 中填写。")
        if not self.api_key:
            raise AIClientError("API 密钥未配置, 请在 设置 → AI 设置 中填写。")
        if not self.model:
            raise AIClientError("模型名称未配置, 请在 设置 → AI 设置 中填写。")

        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        max_retries = 3
        for attempt in range(max_retries + 1):
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                # 429 (限流) 或 5xx (服务端错误): 指数退避重试
                if attempt < max_retries and (e.code == 429 or 500 <= e.code < 600):
                    time.sleep(2 ** attempt)  # 1s, 2s, 4s
                    continue
                detail = detail[:500]
                raise AIClientError(
                    f"HTTP {e.code} {e.reason}: {detail}".strip()) from e
            except urllib.error.URLError as e:
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise AIClientError(f"网络错误: {e.reason}") from e
            except TimeoutError as e:
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise AIClientError("请求超时, 请检查网络或增大超时时间。") from e
            except Exception as e:  # noqa: BLE001
                raise AIClientError(f"调用失败: {e}") from e

            try:
                return json.loads(body)
            except json.JSONDecodeError as e:
                raise AIClientError(f"响应不是合法 JSON: {e}") from e

        raise AIClientError("请求失败: 已达最大重试次数")
