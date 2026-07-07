"""Git 只读操作服务.

对齐 GNOME 版 git_service.vala, 提供以下只读 Git 操作:
- get_status: 获取工作区状态 (git status --porcelain)
- get_working_tree_diff: 获取未暂存的 diff (git diff)
- get_staged_diff: 获取已暂存的 diff (git diff --cached)
- get_log: 获取最近的提交记录 (git log)
- get_commit_diff: 获取指定 commit 的 diff (git show)

所有操作均为只读, 不执行 commit / push / checkout 等写入操作.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class GitCommit:
    """Git 提交数据模型, 对齐 GNOME 版 git_commit.vala."""
    hash: str
    short_hash: str
    author: str
    date: str
    message: str


class GitError(Exception):
    """Git 操作异常."""


def sanitize_git_error(msg: str, max_len: int = 60) -> str:
    """清洗 Git 命令行错误输出, 去除冗余前缀并安全截断.

    对齐 GNOME 版 window.vala 的 Git 错误提示逻辑:
    - 去除 "Git error: " 前缀
    - 去除 "fatal: " / "fatal:" 文案
    - 去除首尾空白
    - 超过 max_len 字符时截断 (Python 按字符截断, 天然 UTF-8 安全)
    """
    if not msg:
        return msg
    display = msg
    if display.startswith("Git error: "):
        display = display[len("Git error: "):]
    display = display.replace("fatal: ", "").replace("fatal:", "")
    display = display.strip()
    if len(display) > max_len:
        display = display[: max_len - 3] + "..."
    return display



def _run_git(args: list[str], cwd: str, timeout: float = 30.0) -> str:
    """执行 git 命令并返回 stdout, 失败时抛出 GitError."""
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise GitError("git 未安装或不在 PATH 中")
    except subprocess.TimeoutExpired:
        raise GitError("git 命令执行超时")
    except Exception as e:
        raise GitError(f"git 执行失败: {e}")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise GitError(stderr or f"git {' '.join(args)} 失败 (exit {result.returncode})")

    return result.stdout


def is_git_repo(cwd: str) -> bool:
    """检查指定目录是否为 Git 仓库."""
    try:
        _run_git(["rev-parse", "--is-inside-work-tree"], cwd, timeout=5.0)
        return True
    except GitError:
        return False


def get_status(cwd: str) -> str:
    """获取工作区状态 (git status --porcelain).

    返回 porcelain 格式的状态字符串, 每行格式: XY <path>
    """
    return _run_git(["status", "--porcelain"], cwd)


def get_working_tree_diff(cwd: str) -> str:
    """获取未暂存的工作区 diff (git diff)."""
    return _run_git(["diff"], cwd)


def get_staged_diff(cwd: str) -> str:
    """获取已暂存的 diff (git diff --cached)."""
    return _run_git(["diff", "--cached"], cwd)


def get_commit_diff(cwd: str, commit_hash: str) -> str:
    """获取指定 commit 的完整 diff (git show)."""
    if not commit_hash or len(commit_hash) < 4:
        raise GitError("无效的 commit hash")
    return _run_git(["show", "--stat", "--patch", commit_hash], cwd)


def get_log(cwd: str, max_count: int = 100) -> list[GitCommit]:
    """获取最近的提交记录.

    使用自定义分隔符解析 git log 输出, 避免 commit message 中的特殊字符干扰.
    """
    SEP = "---FC_SEP---"
    fmt = f"%H{SEP}%h{SEP}%an{SEP}%ai{SEP}%s"
    raw = _run_git(
        ["log", f"--format={fmt}", f"--max-count={max_count}"],
        cwd,
        timeout=15.0,
    )

    commits: list[GitCommit] = []
    for line in raw.strip().splitlines():
        parts = line.split(SEP, 4)
        if len(parts) < 5:
            continue
        full_hash, short_hash, author, date, message = parts
        commits.append(GitCommit(
            hash=full_hash,
            short_hash=short_hash,
            author=author,
            date=date.strip(),
            message=message,
        ))
    return commits


def parse_status_files(status_output: str, cwd: str) -> list[str]:
    """解析 git status --porcelain 输出, 返回变更文件的绝对路径列表.

    porcelain v1 格式: XY <path>
    处理 rename: "old -> new"
    只返回实际存在的普通文件.
    """
    import os

    files: list[str] = []
    for line in status_output.splitlines():
        trimmed = line.strip()
        if len(trimmed) < 4:
            continue
        # XY <path>
        path_part = trimmed[3:].strip()
        # 处理 rename: "old -> new"
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 2)[1]
        abs_path = os.path.join(cwd, path_part)
        if os.path.isfile(abs_path):
            files.append(abs_path)
    return files
