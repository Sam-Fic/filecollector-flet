"""文件内容搜索服务 - 后台线程异步搜索"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable, Optional

from filecollector.utils import safe_read_file
from filecollector.gui_flet.constants import SKIP_DIRS

MAX_FILE_SIZE: int = 2 * 1024 * 1024   # 2 MB
MAX_RESULTS: int = 2000
_BINARY_SNIFF_BYTES: int = 2048


def _is_binary(file_path: str) -> bool:
    """检查文件前 2048 字节是否包含 null 字节。"""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(_BINARY_SNIFF_BYTES)
        return b"\x00" in chunk
    except OSError:
        return True


class SearchService:
    """在后台守护线程中搜索文件内容。

    Parameters
    ----------
    root_dir : str | Path
        搜索根目录。
    query : str
        搜索关键词。
    case_sensitive : bool
        是否区分大小写，默认 False。
    cancel_event : threading.Event | None
        外部传入的取消信号，set() 后搜索会尽快终止。
    on_result : (file_path, rel_path, line_number, line_content) -> None
        每找到一条匹配时的回调。
    on_progress : (scanned, matched) -> None
        每扫描完一个文件后回调，报告已扫描文件数和已匹配数。
    on_finished : (total_scanned, total_matched) -> None
        搜索完成（或取消）后回调。
    """

    def __init__(
        self,
        root_dir: str | Path,
        query: str,
        *,
        case_sensitive: bool = False,
        cancel_event: Optional[threading.Event] = None,
        on_result: Optional[Callable[[str, str, int, str], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_finished: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        self._root = str(Path(root_dir).resolve())
        self._query = query
        self._case_sensitive = case_sensitive
        self._cancel = cancel_event or threading.Event()
        self._on_result = on_result
        self._on_progress = on_progress
        self._on_finished = on_finished
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """启动搜索守护线程。"""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        scanned = 0
        matched = 0
        query = self._query if self._case_sensitive else self._query.lower()

        for dirpath, dirnames, filenames in os.walk(self._root):
            if self._cancel.is_set():
                break

            # 原地修改 dirnames 以跳过忽略目录和隐藏目录
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS and not d.startswith(".")
            ]

            for filename in filenames:
                if self._cancel.is_set():
                    break

                if filename.startswith("."):
                    continue

                full_path = os.path.join(dirpath, filename)

                # 文件大小检查
                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    continue
                if size > MAX_FILE_SIZE or size == 0:
                    continue

                # 二进制文件检查
                if _is_binary(full_path):
                    continue

                # 读取文件内容
                try:
                    content, _encoding = safe_read_file(full_path)
                except Exception:
                    continue

                scanned += 1

                # 逐行搜索
                for line_number, line in enumerate(content.splitlines(), start=1):
                    haystack = line if self._case_sensitive else line.lower()
                    if query in haystack:
                        matched += 1
                        try:
                            rel_path = os.path.relpath(full_path, self._root)
                        except ValueError:
                            rel_path = full_path
                        if self._on_result:
                            self._on_result(full_path, rel_path, line_number, line.rstrip("\n\r"))
                        if matched >= MAX_RESULTS:
                            break

                if self._on_progress:
                    self._on_progress(scanned, matched)

                if matched >= MAX_RESULTS:
                    break

            if self._cancel.is_set() or matched >= MAX_RESULTS:
                break

        if self._on_finished:
            self._on_finished(scanned, matched)
