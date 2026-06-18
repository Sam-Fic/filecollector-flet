"""撤销/重做管理器"""

from __future__ import annotations


class UndoManager:
    """撤销/重做管理器

    使用双重限制防止内存膨胀:
    - ``MAX_UNDO_STEPS``: 撤销步数硬上限
    - ``MAX_STACK_BYTES``: 栈内所有快照的文本字节总量软上限,
      超过时从最旧的快照开始淘汰, 避免大量纯文本块深拷贝导致内存激增.
    """

    MAX_UNDO_STEPS = 100
    # 软容量上限 (字节): 约为 64 MiB, 超过后自动缩减历史步数
    MAX_STACK_BYTES = 64 * 1024 * 1024

    def __init__(self):
        self.undo_stack = []
        self.redo_stack = []

    @staticmethod
    def _estimate_state_bytes(state) -> int:
        """估算单个快照占用的内存字节数.

        主要关注 ``items`` 列表中纯文本块 (``type_="text"``) 的 ``content``
        以及文件条目 ``path`` 的长度, 这些是内存膨胀的主要来源.
        """
        try:
            total = 0
            items = state.get("items", []) if isinstance(state, dict) else []
            for it in items:
                # ItemData 或 dict 均支持 getattr / get
                content = getattr(it, "content", None)
                if content is None and isinstance(it, dict):
                    content = it.get("content")
                if content:
                    total += len(content.encode("utf-8", errors="replace"))
                path = getattr(it, "path", None)
                if path is None and isinstance(it, dict):
                    path = it.get("path")
                if path:
                    total += len(str(path).encode("utf-8", errors="replace"))
            return total
        except Exception:
            return 0

    def _stack_bytes(self) -> int:
        """估算 undo 栈中所有快照的字节总量."""
        return sum(self._estimate_state_bytes(s) for s in self.undo_stack)

    def push(self, state):
        """推入撤销栈

        推入后依次检查步数硬上限和字节软上限, 超出时从栈底 (最旧) 淘汰.
        """
        self.undo_stack.append(state)
        # 步数硬上限
        if len(self.undo_stack) > self.MAX_UNDO_STEPS:
            self.undo_stack.pop(0)
        # 字节软上限: 从最旧的快照开始淘汰, 直到低于阈值或仅剩 1 步
        while len(self.undo_stack) > 1 and self._stack_bytes() > self.MAX_STACK_BYTES:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self, current):
        """撤销"""
        if not self.can_undo:
            return None
        self.redo_stack.append(current)
        return self.undo_stack.pop()

    def redo(self, current):
        """重做"""
        if not self.can_redo:
            return None
        self.undo_stack.append(current)
        return self.redo_stack.pop()

    @property
    def can_undo(self):
        return len(self.undo_stack) > 0

    @property
    def can_redo(self):
        return len(self.redo_stack) > 0

    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()
