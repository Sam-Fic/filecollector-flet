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
        # 本批次已计入 total 的 item (重试同一 item 不重复计数)
        self._counted_set: set[int] = set()

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
        # 单条 item 被取消时触发 (cancel 清队列 + 活跃任务在取消后收尾),
        # 调用方负责把 item.preprocess_status 复位, 避免卡在 PENDING/PROCESSING.
        self.on_item_cancelled: Optional[Callable[[ItemData], None]] = None

    # ------------------------------------------------------------------ 属性
    @property
    def is_paused(self) -> bool:
        return self._is_paused

    # ------------------------------------------------------------------ 公共 API
    def set_executor(self, executor: Callable[[ItemData, "VLMQueueManager"], None]):
        self._executor = executor

    def enqueue(self, item: ItemData) -> None:
        """将条目加入预处理队列 (已在队列中或正在处理则跳过).

        同一 item 重试时不重复计入 total — 用 _counted_set 记录本批次
        已计数的 item, 批次结束 (队列空 + 无活跃) 时重置.
        """
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
            # 仅首次入队时计入 total, 重试不重复计数
            if iid not in self._counted_set:
                self._counted_set.add(iid)
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
        """取消所有待处理任务; 活跃任务继续跑完但结果丢弃, 卡片立即隐藏.

        会触发 on_item_cancelled 回调把每个被取消的 pending item 状态复位
        (避免它们卡在 PENDING). 活跃任务在 notify_finished 中走相同回调.
        同时清掉 _is_paused, 让队列回到干净状态.
        """
        with self._lock:
            self._is_cancelled = True
            self._is_paused = False
            cancelled_pending = list(self._pending_queue)
            self._pending_queue.clear()
            self._pending_set.clear()
            # total 设为 completed + active, 让计数随活跃任务完成自然收敛
            self._total_count = self._completed_count + len(self._active_set)
        # 立即隐藏卡片, 不等活跃任务结束
        self._fire_state(False)
        # 复位 pending item 状态 (在 worker 线程触发, 调用方自行切回 UI 线程)
        for it in cancelled_pending:
            self._fire_item_cancelled(it)

    def check_cancelled(self) -> bool:
        return self._is_cancelled

    def notify_finished(self, item: ItemData) -> None:
        """Worker 调用: 通知单条任务完成 (线程安全, 自动调度下一批)."""
        with self._lock:
            iid = id(item)
            self._active_set.discard(iid)
            self._completed_count += 1
            batch_done = (not self._active_set and not self._pending_queue)
            is_cancelled = self._is_cancelled
            # 取消模式下不发进度信号 (避免重新显示已隐藏的卡片)
            if not is_cancelled:
                self._emit_signals()
            if batch_done:
                # 批次结束: 重置计数器, 下次入队从 0 开始
                self._total_count = 0
                self._completed_count = 0
                self._counted_set.clear()
                self._is_cancelled = False
                self._fire_state(False)
        # 取消模式下活跃任务收尾时, 复位 item 状态 (避免卡在 PROCESSING).
        # 注意: executor 的 cancel-checkpoint 直接调用 notify_finished 不改状态,
        # 此回调负责把 PENDING/PROCESSING/CHECKING 复位为 NONE.
        if is_cancelled:
            self._fire_item_cancelled(item)
        self._try_process_next()

    def has_tasks(self) -> bool:
        with self._lock:
            return (self._total_count > self._completed_count
                    or bool(self._pending_queue)
                    or bool(self._active_set))

    # ------------------------------------------------------------------ 内部
    def _emit_signals(self) -> None:
        """触发进度/状态回调.

        始终在独立线程中执行回调, 避免在 UI 线程同步代码中调用
        control.update() / page.run_task 导致阻塞或死锁.
        """
        completed = self._completed_count
        total = self._total_count
        active = len(self._active_set)
        has_tasks = (
            total > completed
            or bool(self._pending_queue)
            or bool(self._active_set)
        )

        def _fire():
            if self.on_progress:
                try:
                    self.on_progress(completed, total, active)
                except Exception as e:
                    logging.warning(f"VLMQueueManager.on_progress error: {e}")
            if self.on_state_changed:
                try:
                    self.on_state_changed(has_tasks)
                except Exception as e:
                    logging.warning(f"VLMQueueManager.on_state_changed error: {e}")

        threading.Thread(target=_fire, daemon=True).start()

    def _fire_state(self, has_tasks: bool) -> None:
        """直接触发状态回调 (仅用于 cancel 等场景)."""
        if self.on_state_changed:
            try:
                self.on_state_changed(has_tasks)
            except Exception as e:
                logging.warning(f"VLMQueueManager.on_state_changed error: {e}")

    def _fire_item_cancelled(self, item: ItemData) -> None:
        """触发单条 item 取消回调.

        始终在独立线程中执行, 避免 cancel() 从 UI 线程调用时,
        on_item_cancelled 内部的 page.run_task 死锁.
        """
        if not self.on_item_cancelled:
            return

        cb = self.on_item_cancelled

        def _fire():
            try:
                cb(item)
            except Exception as e:
                logging.warning(f"VLMQueueManager.on_item_cancelled error: {e}")

        threading.Thread(target=_fire, daemon=True).start()

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
