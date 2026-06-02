"""左侧文件树组件 - 重构版.

设计目标 (针对原版缺陷逐一修复):
1. **三态复选框 UI 清晰**: 显式定义 QTreeView::indicator 样式,
   使用 SVG 内嵌图像绘制"勾"和"横线"图标, 不依赖系统主题.
2. **三态复选框状态稳定**: 禁用 Qt.ItemIsAutoTristate, 由代码显式管理状态计算.
   避免 Qt 在子项未完全加载时显示错误状态.
3. **文件夹选择 → 列表联动**: 文件夹勾选时, 递归联动所有后代文件, 并
   将每个勾选文件传入 engine. 子项更新后再反向计算所有祖先的状态.
4. **完整三态规则**:
   - 勾选文件夹 → 递归勾选所有后代文件
   - 取消文件夹 → 递归取消所有后代文件
   - 文件夹的所有子项都被勾选 → 父显示 Checked
   - 文件夹的所有子项都未勾选 → 父显示 Unchecked
   - 文件夹的子项混合勾选 → 父显示 PartiallyChecked
5. **稳定持久化**: 状态在 _all_items 字典中按 path 索引, 刷新/展开/重渲染后
   状态一致. get_checked_paths() / set_checked_paths() 对外提供统一接口.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import QColor, QPainter, QBrush, QPen, QPolygon
from PySide6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QStyledItemDelegate, QStyleOptionViewItem,
    QStyle, QApplication, QAbstractItemView,
)

ROLE_PATH = Qt.UserRole + 1
ROLE_IS_DIR = Qt.UserRole + 2
ROLE_IS_PLACEHOLDER = Qt.UserRole + 3


class CheckBoxStyle:
    """复选框三态颜色 (与 style.py 保持一致)."""

    BG = "#ffffff"
    BORDER = "#8a8580"
    BORDER_HOVER = "#1c71d8"
    BORDER_FOCUS = "#1c71d8"
    ACCENT = "#1c71d8"
    ACCENT_DISABLED = "#c5c5c5"
    CHECK = "#ffffff"
    PARTIAL = "#ffffff"


class _TriStateCheckBoxDelegate(QStyledItemDelegate):
    """自绘三态复选框, 避免依赖平台主题导致 checkbox 不可见."""

    SIZE = 16
    PADDING = 4

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        is_checkable = bool(opt.features & QStyleOptionViewItem.HasCheckIndicator)
        check_state = None
        if is_checkable:
            check_state = opt.checkState

        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        bg_brush = None
        if opt.state & QStyle.State_Selected:
            bg_brush = QColor(28, 113, 216, 40)
        elif opt.state & QStyle.State_MouseOver:
            bg_brush = QColor(28, 113, 216, 16)

        rect = opt.rect
        if bg_brush is not None:
            painter.fillRect(rect, bg_brush)

        if is_checkable:
            cb_size = self.SIZE
            cb_rect = rect.adjusted(self.PADDING, (rect.height() - cb_size) // 2, 0, 0)
            cb_rect.setWidth(cb_size)
            cb_rect.setHeight(cb_size)

            if not (opt.state & QStyle.State_Enabled):
                accent = QColor(CheckBoxStyle.ACCENT_DISABLED)
                border = QColor(CheckBoxStyle.ACCENT_DISABLED)
            elif check_state == Qt.Checked or check_state == Qt.PartiallyChecked:
                accent = QColor(CheckBoxStyle.ACCENT)
                border = QColor(CheckBoxStyle.ACCENT)
            else:
                accent = QColor(CheckBoxStyle.BG)
                border = QColor(CheckBoxStyle.BORDER)

            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setBrush(QBrush(accent))
            pen = QPen(border)
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.drawRoundedRect(cb_rect.adjusted(0, 0, -1, -1), 3, 3)

            if check_state == Qt.Checked:
                pen = QPen(QColor(CheckBoxStyle.CHECK))
                pen.setWidthF(2.2)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)
                p1 = cb_rect.adjusted(int(cb_size * 0.20), int(cb_size * 0.50), 0, 0).topLeft()
                p2 = cb_rect.adjusted(int(cb_size * 0.42), int(cb_size * 0.72), 0, 0).bottomLeft()
                p3 = cb_rect.adjusted(int(cb_size * 0.78), int(cb_size * 0.30), 0, 0).topRight()
                painter.drawLine(p1, p2)
                painter.drawLine(p2, p3)
            elif check_state == Qt.PartiallyChecked:
                pen = QPen(QColor(CheckBoxStyle.PARTIAL))
                pen.setWidthF(2.2)
                pen.setCapStyle(Qt.RoundCap)
                painter.setPen(pen)
                line_y = cb_rect.center().y()
                painter.drawLine(
                    cb_rect.adjusted(int(cb_size * 0.25), line_y - cb_rect.y(), 0, 0).topLeft(),
                    cb_rect.adjusted(int(cb_size * 0.75), line_y - cb_rect.y(), 0, 0).topRight(),
                )
            painter.restore()

            text_x = cb_rect.right() + self.PADDING * 2
            text_rect = rect.adjusted(text_x - rect.x(), 0, -self.PADDING, 0)
        else:
            text_rect = rect.adjusted(self.PADDING, 0, -self.PADDING, 0)

        text_color = QColor("#2e2e2e")
        if not (opt.state & QStyle.State_Enabled):
            text_color = QColor("#b0afad")
        painter.setPen(text_color)
        painter.setFont(opt.font)
        fm = opt.fontMetrics
        elided = fm.elidedText(opt.text, Qt.ElideRight, text_rect.width())
        painter.drawText(
            text_rect,
            int(Qt.AlignVCenter | Qt.AlignLeft),
            elided,
        )

    def editorEvent(self, event, model, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        is_checkable = bool(opt.features & QStyleOptionViewItem.HasCheckIndicator)
        if not is_checkable:
            return False
        if event.type() == event.Type.MouseButtonRelease and event.button() == Qt.LeftButton:
            cb_size = self.SIZE
            cb_rect = opt.rect.adjusted(self.PADDING, (opt.rect.height() - cb_size) // 2, 0, 0)
            cb_rect.setWidth(cb_size)
            cb_rect.setHeight(cb_size)
            if cb_rect.contains(event.pos()):
                current = opt.checkState
                if current == Qt.Checked:
                    new_state = Qt.Unchecked
                elif current == Qt.PartiallyChecked:
                    new_state = Qt.Checked
                else:
                    new_state = Qt.Checked
                model.setData(index, new_state, Qt.CheckStateRole)
                return True
        return False


class FileTreeWidget(QTreeWidget):
    """左侧文件树组件, 自管三态逻辑与懒加载."""

    checked_files_changed = Signal()
    work_dir_loaded = Signal()

    IGNORE_DIRS = {
        ".git", "node_modules", "__pycache__", ".svn", ".hg",
        "venv", ".idea", ".vscode", "build", "dist", ".cache",
    }

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setAnimated(True)
        self.setIndentation(20)
        self.setExpandsOnDoubleClick(False)
        self.setMinimumWidth(200)
        self.setSelectionMode(QTreeWidget.SingleSelection)
        self.setUniformRowHeights(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setRootIsDecorated(True)
        self.setItemsExpandable(True)
        self.setMouseTracking(True)

        self._delegate = _TriStateCheckBoxDelegate(self)
        self.setItemDelegate(self._delegate)

        self._loading = False
        self._loaded_dirs: set[str] = set()
        self._all_items: dict[str, QTreeWidgetItem] = {}
        self._pending_checked: set[str] = set()

        self.setStyleSheet(self._build_stylesheet())

        self.itemChanged.connect(self._on_item_changed)
        self.itemExpanded.connect(self._on_item_expanded)
        self.itemClicked.connect(self._on_item_clicked)

    # ------------------------------------------------------------------
    # Branch indicator (折叠/展开箭头) 自绘, 避免依赖平台主题
    # ------------------------------------------------------------------
    def drawBranches(self, painter: QPainter, rect: QRect, index) -> None:
        item = self.itemFromIndex(index)
        if item is None or not item.data(0, ROLE_IS_DIR):
            return
        if item.childCount() == 0:
            return
        is_expanded = item.isExpanded()
        cx = rect.x() + rect.width() // 2
        cy = rect.y() + rect.height() // 2
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(CheckBoxStyle.BORDER))
        try:
            if is_expanded:
                poly = QPolygon([
                    QPoint(cx - 4, cy - 2),
                    QPoint(cx + 4, cy - 2),
                    QPoint(cx, cy + 3),
                ])
            else:
                poly = QPolygon([
                    QPoint(cx - 2, cy - 4),
                    QPoint(cx - 2, cy + 4),
                    QPoint(cx + 3, cy),
                ])
            painter.drawPolygon(poly)
        finally:
            painter.restore()

    # ------------------------------------------------------------------
    # 样式
    # ------------------------------------------------------------------
    def _build_stylesheet(self) -> str:
        return """
        QTreeWidget {
            background: transparent;
            border: none;
            outline: 0;
            color: #2e2e2e;
            font-size: 13px;
        }
        QTreeWidget::item {
            padding: 4px 4px;
            border-radius: 4px;
        }
        QTreeWidget::item:hover {
            background-color: rgba(28, 113, 216, 0.08);
        }
        QTreeWidget::item:selected {
            background-color: rgba(28, 113, 216, 0.20);
        }
        QTreeWidget::branch {
            background: transparent;
        }
        """

    # ------------------------------------------------------------------
    # 工作目录
    # ------------------------------------------------------------------
    def set_work_dir(self, work_dir: Optional[Path]) -> None:
        """重置树并显示给定工作目录."""
        self._loading = True
        try:
            self.clear()
            self._loaded_dirs.clear()
            self._all_items.clear()
            self._pending_checked.clear()

            if not work_dir:
                return
            work_dir = Path(work_dir)
            if not work_dir.exists() or not work_dir.is_dir():
                return

            root = QTreeWidgetItem(self)
            root.setText(0, work_dir.name)
            root.setData(0, ROLE_PATH, str(work_dir))
            root.setData(0, ROLE_IS_DIR, True)
            root.setFlags(
                root.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
            )
            root.setCheckState(0, Qt.Unchecked)

            self._populate_dir(root, work_dir)
            self._loaded_dirs.add(str(work_dir))
            self._all_items[str(work_dir)] = root
            root.setExpanded(True)
        finally:
            self._loading = False
        self.work_dir_loaded.emit()

    def work_dir(self) -> Optional[str]:
        if self.topLevelItemCount() == 0:
            return None
        return self.topLevelItem(0).data(0, ROLE_PATH)

    # ------------------------------------------------------------------
    # 内部: 填充目录 (单层)
    # ------------------------------------------------------------------
    def _populate_dir(self, parent_item: QTreeWidgetItem, dir_path: Path) -> None:
        try:
            entries = sorted(
                dir_path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower())
            )
        except (PermissionError, FileNotFoundError):
            return

        for entry in entries:
            if entry.name.startswith(".") and entry.is_dir():
                continue

            item = QTreeWidgetItem(parent_item)
            item.setText(0, entry.name)
            item.setData(0, ROLE_PATH, str(entry))

            if entry.is_dir():
                if entry.name in self.IGNORE_DIRS:
                    parent_item.removeChild(item)
                    continue
                item.setData(0, ROLE_IS_DIR, True)
                item.setFlags(
                    item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
                )
                item.setCheckState(0, Qt.Unchecked)
                placeholder = QTreeWidgetItem(item)
                placeholder.setText(0, "...")
                placeholder.setData(0, ROLE_IS_PLACEHOLDER, True)
                placeholder.setFlags(Qt.NoItemFlags)
            else:
                item.setData(0, ROLE_IS_DIR, False)
                item.setFlags(
                    item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
                )
                item.setCheckState(0, Qt.Unchecked)

            self._all_items[str(entry)] = item

    # ------------------------------------------------------------------
    # 事件: 展开时懒加载
    # ------------------------------------------------------------------
    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        if not item.data(0, ROLE_IS_DIR):
            return
        dir_path_str = item.data(0, ROLE_PATH)
        if not dir_path_str or dir_path_str in self._loaded_dirs:
            self._apply_pending_to_loaded(item)
            return
        dir_path = Path(dir_path_str)
        if not dir_path.is_dir():
            return

        self._remove_placeholder(item)
        self._loading = True
        try:
            self._populate_dir(item, dir_path)
            self._loaded_dirs.add(dir_path_str)
            self._apply_pending_to_loaded(item)
        finally:
            self._loading = False

    def _apply_pending_to_loaded(self, item: QTreeWidgetItem) -> None:
        """将 _pending_checked 中已可见的路径应用到树."""
        if not self._pending_checked:
            return
        matched = []
        for i in range(item.childCount()):
            child = item.child(i)
            if child.data(0, ROLE_IS_PLACEHOLDER):
                continue
            if not child.text(0):
                continue
            p = child.data(0, ROLE_PATH)
            if p in self._pending_checked:
                if not child.data(0, ROLE_IS_DIR):
                    self._loading = True
                    try:
                        child.setCheckState(0, Qt.Checked)
                    finally:
                        self._loading = False
                    self._update_ancestor_states(child)
                    matched.append(p)
            if child.data(0, ROLE_IS_DIR):
                self._apply_pending_to_loaded(child)
        self._pending_checked -= set(matched)

    def _remove_placeholder(self, item: QTreeWidgetItem) -> None:
        for i in range(item.childCount() - 1, -1, -1):
            child = item.child(i)
            if child.data(0, ROLE_IS_PLACEHOLDER):
                item.removeChild(child)

    # ------------------------------------------------------------------
    # 事件: 单击 (切换展开/折叠)
    # ------------------------------------------------------------------
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        if self._loading:
            return
        if not item.data(0, ROLE_IS_DIR):
            return
        cb_size = _TriStateCheckBoxDelegate.SIZE
        padding = _TriStateCheckBoxDelegate.PADDING
        index = self.indexFromItem(item, column)
        rect = self.visualRect(index)
        cb_rect = rect.adjusted(padding, (rect.height() - cb_size) // 2, 0, 0)
        cb_rect.setWidth(cb_size)
        cb_rect.setHeight(cb_size)
        pos = self.mapFromGlobal(self.cursor().pos())
        if cb_rect.contains(pos):
            return
        item.setExpanded(not item.isExpanded())

    # ------------------------------------------------------------------
    # 事件: 复选框状态变化 (核心三态逻辑)
    # ------------------------------------------------------------------
    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """用户操作触发的状态变化."""
        if self._loading or column != 0:
            return
        if not item.flags() & Qt.ItemIsUserCheckable:
            return
        if item.data(0, ROLE_IS_PLACEHOLDER):
            return

        new_state = item.checkState(0)
        is_dir = bool(item.data(0, ROLE_IS_DIR))

        self._loading = True
        try:
            if is_dir:
                if new_state == Qt.PartiallyChecked:
                    target = Qt.Checked
                else:
                    target = new_state
                if target != new_state:
                    item.setCheckState(0, target)
                self._propagate_dir_state(item, target)
            self._update_ancestor_states(item)
        finally:
            self._loading = False

        self.checked_files_changed.emit()

    def _propagate_dir_state(
        self, dir_item: QTreeWidgetItem, state: Qt.CheckState
    ) -> None:
        """将文件夹 state 递归应用到所有后代文件 (系统级, 静默)."""
        self.blockSignals(True)
        try:
            self._propagate_dir_state_impl(dir_item, state)
        finally:
            self.blockSignals(False)

    def _propagate_dir_state_impl(
        self, dir_item: QTreeWidgetItem, state: Qt.CheckState
    ) -> None:
        for i in range(dir_item.childCount()):
            child = dir_item.child(i)
            if child.data(0, ROLE_IS_PLACEHOLDER):
                continue
            if not child.text(0):
                continue
            if child.data(0, ROLE_IS_DIR):
                self._propagate_dir_state_impl(child, state)
            child.setCheckState(0, state)

    def _update_ancestor_states(self, item: QTreeWidgetItem) -> None:
        """反向计算所有祖先文件夹的状态 (系统级, 静默)."""
        parent = item.parent()
        if parent is None:
            return
        self.blockSignals(True)
        try:
            while parent is not None and parent.data(0, ROLE_IS_DIR):
                new_state = self._calculate_dir_state(parent)
                if parent.checkState(0) != new_state:
                    parent.setCheckState(0, new_state)
                parent = parent.parent()
        finally:
            self.blockSignals(False)

    def _calculate_dir_state(self, dir_item: QTreeWidgetItem) -> Qt.CheckState:
        """基于所有后代文件 (叶子) 的状态计算文件夹状态.

        如果存在尚未加载的子目录, 其状态视为未知, 父目录应展示为
        PartiallyChecked.
        """
        states: list[Qt.CheckState] = []
        if not self._collect_leaf_states(dir_item, states):
            return Qt.PartiallyChecked
        if not states:
            return Qt.Unchecked
        checked = sum(1 for s in states if s == Qt.Checked)
        if checked == 0:
            return Qt.Unchecked
        if checked == len(states):
            return Qt.Checked
        return Qt.PartiallyChecked

    def _collect_leaf_states(
        self, item: QTreeWidgetItem, states: list[Qt.CheckState]
    ) -> bool:
        """返回 False 表示存在未加载的子目录, 状态不确定."""
        for i in range(item.childCount()):
            child = item.child(i)
            if child.data(0, ROLE_IS_PLACEHOLDER):
                continue
            if not child.text(0):
                continue
            if child.data(0, ROLE_IS_DIR):
                path_str = child.data(0, ROLE_PATH)
                if path_str not in self._loaded_dirs:
                    return False
                if not self._collect_leaf_states(child, states):
                    return False
            else:
                states.append(child.checkState(0))
        return True

    # ------------------------------------------------------------------
    # 公共 API: 状态查询
    # ------------------------------------------------------------------
    def get_checked_paths(self) -> set[str]:
        """返回所有勾选文件的绝对路径集合."""
        result: set[str] = set()
        for path, item in self._all_items.items():
            if item.data(0, ROLE_IS_DIR):
                continue
            if item.data(0, ROLE_IS_PLACEHOLDER):
                continue
            if item.checkState(0) == Qt.Checked:
                result.add(path)
        return result

    def get_unchecked_paths(self) -> set[str]:
        """返回所有未勾选文件的绝对路径集合 (用于卸载)."""
        result: set[str] = set()
        for path, item in self._all_items.items():
            if item.data(0, ROLE_IS_DIR):
                continue
            if item.data(0, ROLE_IS_PLACEHOLDER):
                continue
            if item.checkState(0) != Qt.Checked:
                result.add(path)
        return result

    def set_checked_paths(self, paths: set[str]) -> None:
        """根据路径集合恢复勾选状态.

        对于尚未展开的子目录, 路径会被加入 _pending_checked, 待该子目录
        被懒加载时再应用.
        """
        self._loading = True
        try:
            self._set_all_states_recursive(self.invisibleRootItem(), Qt.Unchecked)
            self._pending_checked.clear()

            paths = set(paths)
            applied = set()
            for p in paths:
                item = self._all_items.get(p)
                if item and not item.data(0, ROLE_IS_DIR):
                    item.setCheckState(0, Qt.Checked)
                    applied.add(p)

            for p in paths - applied:
                self._pending_checked.add(p)

            for p in applied:
                item = self._all_items.get(p)
                if item:
                    self._update_ancestor_states(item)

            for p in paths - applied:
                self._loading = True
                try:
                    self._eager_load_for_path(p)
                finally:
                    self._loading = True
                item = self._all_items.get(p)
                if item and not item.data(0, ROLE_IS_DIR):
                    item.setCheckState(0, Qt.Checked)
                    self._update_ancestor_states(item)
                    self._pending_checked.discard(p)
        finally:
            self._loading = False
        self.checked_files_changed.emit()

    def _eager_load_for_path(self, file_path: str) -> None:
        """展开 file_path 所在目录链 (仅在 set_checked_paths 中使用).

        自顶向下逐级调用 _on_item_expanded, 避免子目录先于父目录被填充
        导致 _all_items 缺失. p.parents 是 [近, 远], 需 reverse 后才能
        从根目录向下逐级展开.
        """
        p = Path(file_path)
        for ancestor in reversed(p.parents):
            s = str(ancestor)
            if s in self._loaded_dirs:
                continue
            item = self._all_items.get(s)
            if item is None:
                continue
            if not item.data(0, ROLE_IS_DIR):
                continue
            self._on_item_expanded(item)

    def clear_all_checks(self) -> None:
        """清除所有勾选状态."""
        self._loading = True
        try:
            self._set_all_states_recursive(self.invisibleRootItem(), Qt.Unchecked)
        finally:
            self._loading = False
        self.checked_files_changed.emit()

    def _set_all_states_recursive(
        self, item: QTreeWidgetItem, state: Qt.CheckState
    ) -> None:
        for i in range(item.childCount()):
            child = item.child(i)
            if child.data(0, ROLE_IS_PLACEHOLDER):
                continue
            child.setCheckState(0, state)
            self._set_all_states_recursive(child, state)

    # ------------------------------------------------------------------
    # 公共 API: 搜索
    # ------------------------------------------------------------------
    def filter_items(self, keyword: str) -> None:
        keyword = keyword.strip().lower()
        for i in range(self.topLevelItemCount()):
            self._filter_item(self.topLevelItem(i), keyword)

    def _filter_item(self, item: QTreeWidgetItem, keyword: str) -> bool:
        match = not keyword or keyword in item.text(0).lower()
        child_match = False
        for i in range(item.childCount()):
            child = item.child(i)
            if child.data(0, ROLE_IS_PLACEHOLDER):
                continue
            if self._filter_item(child, keyword):
                child_match = True
        item.setHidden(not (match or child_match))
        if match or child_match:
            self._expand_parents(item)
        return match or child_match

    def _expand_parents(self, item: QTreeWidgetItem) -> None:
        parent = item.parent()
        while parent is not None:
            if parent.isHidden():
                parent.setHidden(False)
            parent = parent.parent()
