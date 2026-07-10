"""多格式导出服务 (对齐 GNOME 版 multi_format_exporter.vala).

支持的格式:
- Markdown (.md)   : # 文件名 作 H1, ```lang ... ``` 包裹代码
- JSON (.json)     : 结构化数组, 含 path/content/language/status 等字段
- JSONL (.jsonl)   : 每行一个 JSON 对象, 便于流式 RAG 管道
- Jupyter (.ipynb) : text 项→markdown cell, 代码文件→code cell

所有格式共用 resolve_items() 一次性把 missing/binary/too_large 等情况归一化,
避免每种格式各自重复处理。preprocessed_content (VLM 转写后的 Markdown) 优先使用.
"""

from __future__ import annotations

import datetime
import json
import os
from enum import Enum
from pathlib import Path
from typing import Optional

from filecollector.models import ItemData
from filecollector.utils import safe_read_file, display_path

MAX_FILE_CONTENT_SIZE = 10 * 1024 * 1024  # 10 MB


class ItemKind(Enum):
    OK = "ok"               # 文本内容已就绪, content 字段可用
    MISSING = "missing"     # 文件不存在
    BINARY = "binary"       # 检测到 NULL 字节, 视为二进制
    TOO_LARGE = "too_large" # 超过 MAX_FILE_CONTENT_SIZE
    READ_ERROR = "read_error"


class ResolvedItem:
    """单条 item 解析结果 (跨格式共用)."""

    __slots__ = (
        "source", "display_path", "content", "error_message", "kind", "language",
    )

    def __init__(self, source: ItemData):
        self.source = source
        self.display_path: str = ""
        self.content: Optional[str] = None
        self.error_message: Optional[str] = None
        self.kind: ItemKind = ItemKind.OK
        self.language: str = ""


# ─── 入口 ────────────────────────────────────────────────────────────

def export_markdown(
    file_path: str,
    items: list[ItemData],
    use_absolute: bool,
    show_header: bool,
    work_dir,
) -> None:
    resolved = resolve_items(items, use_absolute, work_dir)
    parts: list[str] = []

    if show_header and work_dir is not None:
        parts.append(f"# 工作目录: {work_dir}\n")

    first = True
    for ri in resolved:
        if not first:
            parts.append("\n\n")
        first = False

        if ri.source.type == "text":
            parts.append(ri.content or "")
            continue

        parts.append(f"# {ri.display_path}\n\n")
        if ri.kind is ItemKind.OK:
            parts.append(f"```{ri.language}\n")
            parts.append(ri.content or "")
            if not (ri.content or "").endswith("\n"):
                parts.append("\n")
            parts.append("```\n")
        else:
            parts.append("```\n")
            parts.append(ri.error_message or "")
            parts.append("\n```\n")

    _write_text_file(file_path, "".join(parts))


def export_json(
    file_path: str,
    items: list[ItemData],
    use_absolute: bool,
    show_header: bool,
    work_dir,
) -> None:
    resolved = resolve_items(items, use_absolute, work_dir)
    root: dict = {}

    if show_header and work_dir is not None:
        root["work_dir"] = str(work_dir)
    root["generated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    root["items"] = [_item_to_dict(ri) for ri in resolved]

    _write_text_file(file_path, json.dumps(root, ensure_ascii=False, indent=2))


def export_jsonl(
    file_path: str,
    items: list[ItemData],
    use_absolute: bool,
    show_header: bool,
    work_dir,
) -> None:
    resolved = resolve_items(items, use_absolute, work_dir)
    lines = [json.dumps(_item_to_dict(ri), ensure_ascii=False) for ri in resolved]
    _write_text_file(file_path, "\n".join(lines) + ("\n" if lines else ""))


def export_ipynb(
    file_path: str,
    items: list[ItemData],
    use_absolute: bool,
    show_header: bool,
    work_dir,
) -> None:
    resolved = resolve_items(items, use_absolute, work_dir)

    cells: list[dict] = []

    if show_header and work_dir is not None:
        cells.append({
            "cell_type": "markdown",
            "metadata": {},
            "source": [
                "# FileCollector Export\n",
                "\n",
                f"工作目录: `{work_dir}`\n",
            ],
        })

    for ri in resolved:
        as_code = (
            ri.source.type == "file"
            and ri.kind is ItemKind.OK
            and _is_code_language(ri.language)
        )
        cell: dict = {"cell_type": "code" if as_code else "markdown"}

        if as_code:
            cell["execution_count"] = None
            cell["outputs"] = []
        cell["metadata"] = {}

        source_lines: list[str] = []
        if ri.source.type == "text":
            source_lines = _split_source_lines(ri.content or "")
        elif ri.kind is ItemKind.OK:
            source_lines.append(f"# {ri.display_path}\n\n")
            if as_code:
                source_lines.extend(_split_source_lines(ri.content or ""))
            elif ri.language in ("md", "markdown"):
                source_lines.extend(_split_source_lines(ri.content or ""))
            else:
                source_lines.append(f"```{ri.language}\n")
                source_lines.extend(_split_source_lines(ri.content or ""))
                if not (ri.content or "").endswith("\n"):
                    source_lines.append("\n")
                source_lines.append("```\n")
        else:
            source_lines.append(f"# {ri.display_path}\n\n")
            source_lines.append(f"> {ri.error_message or ''}\n")

        cell["source"] = source_lines
        cells.append(cell)

    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }
    _write_text_file(file_path, json.dumps(nb, ensure_ascii=False, indent=2))


# ─── 共用解析 ────────────────────────────────────────────────────────

def resolve_items(
    items: list[ItemData],
    use_absolute: bool,
    work_dir,
) -> list[ResolvedItem]:
    result: list[ResolvedItem] = []
    for data in items:
        ri = ResolvedItem(data)

        if data.type == "text":
            ri.content = data.content or ""
            ri.kind = ItemKind.OK
            result.append(ri)
            continue

        # file 项
        ri.display_path = display_path(
            data.path or "",
            force_absolute=data.force_absolute,
            use_absolute=use_absolute,
            work_dir=work_dir,
        )
        ri.language = _extract_language(data.path or "")

        if not data.path or not os.path.exists(data.path):
            ri.kind = ItemKind.MISSING
            ri.error_message = f"[缺失文件: {data.path}]"
            result.append(ri)
            continue

        if data.preprocessed_content:
            ri.kind = ItemKind.OK
            ri.content = data.preprocessed_content
            result.append(ri)
            continue

        try:
            file_size = os.path.getsize(data.path)
        except OSError as e:
            ri.kind = ItemKind.READ_ERROR
            ri.error_message = f"[无法获取文件信息: {e}]"
            result.append(ri)
            continue

        if file_size > MAX_FILE_CONTENT_SIZE:
            ri.kind = ItemKind.TOO_LARGE
            ri.error_message = (
                f"[文件过大 ({_format_size(file_size)}), 已跳过内容读取]"
            )
            result.append(ri)
            continue

        try:
            with open(data.path, "rb") as bf:
                raw = bf.read()
            if b"\x00" in raw[:8192]:
                ri.kind = ItemKind.BINARY
                ri.error_message = "[检测到二进制文件: 已跳过文本内容读取]"
                result.append(ri)
                continue

            try:
                content, _ = safe_read_file(data.path)
            except Exception:
                content = raw.decode("utf-8", errors="replace")
            ri.kind = ItemKind.OK
            ri.content = content
            result.append(ri)
        except OSError as e:
            ri.kind = ItemKind.READ_ERROR
            ri.error_message = f"[读取文件失败: {e}]"
            result.append(ri)

    return result


# ─── helpers ─────────────────────────────────────────────────────────

def _item_to_dict(ri: ResolvedItem) -> dict:
    if ri.source.type == "text":
        return {"type": "text", "content": ri.content or ""}
    d: dict = {
        "type": "file",
        "path": ri.display_path,
        "language": ri.language,
        "status": ri.kind.value,
    }
    if ri.kind is ItemKind.OK:
        d["content"] = ri.content or ""
    elif ri.error_message is not None:
        d["note"] = ri.error_message
    return d


def _split_source_lines(text: str) -> list[str]:
    """Jupyter source 字段: list of strings, 每行末尾保留 \\n (最后一行除外)."""
    if not text:
        return []
    parts = text.split("\n")
    return [p + "\n" for p in parts[:-1]] + (
        [parts[-1]] if parts[-1] else []
    )


def _is_code_language(lang: str) -> bool:
    return lang.lower() in {
        "py", "python",
        "js", "javascript", "mjs",
        "ts", "typescript",
        "vala",
        "c", "h",
        "cpp", "hpp", "cc", "cxx",
        "rs", "rust",
        "go",
        "java",
        "kt", "kts",
        "swift",
        "rb", "ruby",
        "php",
        "sh", "bash", "zsh",
        "sql",
        "r",
        "lua",
        "pl", "perl",
        "scala",
        "hs", "haskell",
        "clj",
        "ex", "exs",
        "jl",
        "dart",
        "cs", "csharp",
        "fs",
        "vim",
        "ps1",
    }



def _extract_language(path: str) -> str:
    lower = path.lower()
    dot = lower.rfind(".")
    if dot < 0 or dot == len(lower) - 1:
        return ""
    return lower[dot + 1:]


def _format_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def _write_text_file(path: str, content: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8", errors="replace")
        tmp.replace(out)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
