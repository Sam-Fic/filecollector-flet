import copy


class UndoState:
    def __init__(self, items, checked_paths, use_absolute, show_header):
        self.items = [copy.copy(i) for i in items]
        self.checked_paths = set(checked_paths)
        self.use_absolute = use_absolute
        self.show_header = show_header


class UndoManager:
    def __init__(self):
        self.undo_stack = []
        self.redo_stack = []

    def push(self, state):
        self.undo_stack.append(state)
        self.redo_stack.clear()

    def undo(self, current):
        if not self.can_undo:
            return None
        self.redo_stack.append(current)
        return self.undo_stack.pop()

    def redo(self, current):
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
