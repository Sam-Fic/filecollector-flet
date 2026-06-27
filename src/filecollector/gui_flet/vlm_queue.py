"""VLM 预处理队列管理器 (并发控制、暂停/取消).

对齐 GNOME 版 vlm_queue.vala:
- 有界并发 (默认 3 个同时执行)
- 暂停 / 恢复 / 取消
- 进度回调 (completed, total, active)
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Callable, Optional

from filecollector.models import ItemData, PreprocessStatus


class VLMQueueManager:
    """VLM 预处理队列: 串行入队, 有界并发执行."""

    def __init__(self, max_concurrency: int = 3):
        self.max_concurrency = max_concurrency

        self._pending_queue: deque[ItemData] = deque()
        self._pending_set: set[int] = set()   # id(item)
        self._active_set: set[int] = set()

        self._completed_count = 0
        self._total_count = 0

        self._is_paused = False
        self._is_cancelled = False

        self._lock = threading.Lock()

        self._executor: Optional[Callable[[
            ItemData, "VLMQueueManager"], None]] = None

        # 回调 (在 worker 线程中触发, 调用方负责切回 UI 线程)
        self.on_progress: Optional[Callable[[int, int, int], None]] = None
        self.on_state_changed: Optional[Callable[[bool], None]] = None

    # ------------------------------------------------------------------ 属性
    @property
    def is_paused(self) -> bool:
        return self._is_paused

    # ------------------------------------------------------------------ 公共 API
    def set_executor(self, executor: Callable[[ItemData, "VLMQueueManager"], None]):
        self._executor = executor

    def enqueue(self, item: ItemData) -> None:
        """将条目加入预处理队列 (已在队列中或正在处理则跳过)."""
        with self._lock:
            iid = id(item)
            if iid in self._active_set or iid in self._pending_set:
                return
            if item.preprocess_status in (
                PreprocessStatus.PROCESSING, PreprocessStatus.CHECKING
            ):
                return

            self._pending_queue.append(item)
            self._pending_set.add(iid)
            self._total_count += 1
            self._is_cancelled = False
            self._emit_signals()
        self._try_process_next()

    def pause(self) -> None:
        self._is_paused = True

    def resume(self) -> None:
        if self._is_paused:
            self._is_paused = False
            self._try_process_next()

    def cancel(self) -> None:
        with self._lock:
            self._is_cancelled = True
            self._pending_queue.clear()
            self._pending_set.clear()
            self._total_count = self._completed_count
            self._emit_signals()
            if not self._active_set:
                self._fire_state(False)

    def check_cancelled(self) -> bool:
        return self._is_cancelled

    def notify_finished(self, item: ItemData) -> None:
        """Worker 调用: 通知单条任务完成 (线程安全, 自动调度下一批)."""
        with self._lock:
            iid = id(item)
            self._active_set.discard(iid)
            self._completed_count += 1
            self._emit_signals()
            if not self._active_set and not self._pending_queue:
                self._fire_state(False)
        self._try_process_next()

    def has_tasks(self) -> bool:
        with self._lock:
            return (self._total_count > self._completed_count
                    or bool(self._pending_queue)
                    or bool(self._active_set))

    # ------------------------------------------------------------------ 内部
    def _emit_signals(self) -> None:
        completed = self._completed_count
        total = self._total_count
        active = len(self._active_set)
        if self.on_progress:
            try:
                self.on_progress(completed, total, active)
            except Exception as e:
                logging.warning(f"VLMQueueManager.on_progress error: {e}")
        self._fire_state(self.has_tasks())

    def _fire_state(self, has_tasks: bool) -> None:
        if self.on_state_changed:
            try:
                self.on_state_changed(has_tasks)
            except Exception as e:
                logging.warning(f"VLMQueueManager.on_state_changed error: {e}")

    def _try_process_next(self) -> None:
        if self._is_paused or self._is_cancelled:
            return
        while True:
            with self._lock:
                if len(self._active_set) >= self.max_concurrency:
                    return
                if not self._pending_queue:
                    return
                item = self._pending_queue.popleft()
                self._pending_set.discard(id(item))
                self._active_set.add(id(item))
                self._emit_signals()
            self._execute_task_in_background(item)

    def _execute_task_in_background(self, item: ItemData) -> None:
        if self._executor is None:
            self.notify_finished(item)
            return

        def _worker():
            try:
                self._executor(item, self)
            except Exception as e:
                logging.warning(f"VLMQueueManager executor error: {e}")
                item.preprocess_status = PreprocessStatus.FAILED
                self.notify_finished(item)

        t = threading.Thread(target=_worker, daemon=True,
                             name="vlm-queue-task")
        t.start()
