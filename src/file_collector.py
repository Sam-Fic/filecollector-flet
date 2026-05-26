#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileCollector - 现代文件收集与编排工具 (PySide6版)
跨平台支持 Windows / macOS / Linux
功能：
- 懒加载目录树，可勾选文件加入编排列表
- 手动添加外部文件（强制绝对路径）
- 拖拽文件到编排列表，列表内拖拽排序
- 插入自定义文字，双击编辑
- 预览文件/文字内容
- 相对/绝对路径输出，可选头部注释
- 项目保存/加载
- 自动编码检测
"""

import sys
import os
import json
import datetime
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QMimeData, QUrl
from PySide6.QtGui import QAction, QFont, QDragEnterEvent, QDropEvent, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMenuBar, QMenu, QToolBar, QStatusBar,
    QSplitter, QTreeWidget, QTreeWidgetItem, QListWidget, QListWidgetItem,
    QTextEdit, QPushButton, QRadioButton, QCheckBox, QLabel, QVBoxLayout,
    QHBoxLayout, QWidget, QFileDialog, QMessageBox, QInputDialog, QDialog,
    QDialogButtonBox, QPlainTextEdit, QButtonGroup, QFrame, QStyle
)

# 可选编码检测
try:
    import chardet
    CHARDET_AVAILABLE = True
except ImportError:
    CHARDET_AVAILABLE = False


# ----------------------------------------------------------------------
# 工具函数：编码检测与安全读取
# ----------------------------------------------------------------------
def detect_encoding(file_path, num_bytes=10000):
    if not CHARDET_AVAILABLE:
        return None
    try:
        with open(file_path, 'rb') as f:
            raw = f.read(num_bytes)
        result = chardet.detect(raw)
        if result and result['confidence'] > 0.7:
            return result['encoding']
    except Exception:
        pass
    return None


def safe_read_file(file_path, max_preview_lines=None):
    """返回 (content, encoding) 元组，用于预览可限制行数"""
    encodings_to_try = ['utf-8', 'gbk', 'latin-1']
    detected = detect_encoding(file_path)
    if detected and detected.lower() not in [e.lower() for e in encodings_to_try]:
        encodings_to_try.insert(0, detected)

    for enc in encodings_to_try:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                if max_preview_lines is None:
                    content = f.read()
                else:
                    lines = []
                    for i, line in enumerate(f):
                        if i >= max_preview_lines:
                            break
                        lines.append(line)
                    content = ''.join(lines)
            return content, enc
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            continue
    raise RuntimeError(f"无法解码文件: {file_path}")


# ----------------------------------------------------------------------
# 自定义文字编辑对话框
# ----------------------------------------------------------------------
class TextEditDialog(QDialog):
    def __init__(self, parent=None, title="编辑文字", initial_text=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(500, 400)
        self.setMinimumSize(300, 200)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("请输入文字:"))

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlainText(initial_text)
        layout.addWidget(self.text_edit)

        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_text(self):
        return self.text_edit.toPlainText().strip()


# ----------------------------------------------------------------------
# 自定义列表条目（用于存储数据）
# ----------------------------------------------------------------------
class ItemData:
    def __init__(self, type_, path=None, content=None, force_absolute=False):
        self.type = type_          # "file" or "text"
        self.path = path           # 文件绝对路径（字符串）
        self.force_absolute = force_absolute
        self.content = content     # 文字内容


# ----------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------
class FileCollectorApp(QMainWindow):
    # 信号：更新状态栏
    status_message = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FileCollector - 文件收集与编排工具")
        self.resize(1300, 780)
        self.setMinimumSize(950, 500)

        # ---- 数据模型 ----
        self.work_dir = None                     # Path对象
        self.items = []                          # list of ItemData
        self.checked_paths = set()               # 树中勾选的文件绝对路径（字符串）
        self.tree_loading_dirs = set()           # 已加载子节点的目录路径，用于懒加载
        self.ignore_dirs = {'.git', 'node_modules', '__pycache__',
                            '.svn', '.hg', 'venv', '.idea', '.vscode'}

        # ---- 界面状态 ----
        self.project_file = None
        self.use_absolute = False
        self.show_header = False

        # ---- 设置全局字体（高分屏友好） ----
        font = QFont()
        font.setPointSize(10)   # 稍大一点，清晰
        QApplication.setFont(font)

        # ---- 构建界面 ----
        self._setup_menu_bar()
        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_status_bar()
        self._connect_signals()

        # 初始状态
        self._update_path_mode_ui()
        self._refresh_tree()  # 空树

    # ==================================================================
    # 菜单栏
    # ==================================================================
    def _setup_menu_bar(self):
        menu_bar = self.menuBar()

        # 项目菜单
        project_menu = menu_bar.addMenu("项目(&P)")
        load_action = QAction("打开项目...", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self.load_project)
        project_menu.addAction(load_action)

        save_action = QAction("保存项目", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_project)
        project_menu.addAction(save_action)

        save_as_action = QAction("项目另存为...", self)
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self.save_project_as)
        project_menu.addAction(save_as_action)

        project_menu.addSeparator()
        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        project_menu.addAction(exit_action)

        # 帮助菜单
        help_menu = menu_bar.addMenu("帮助(&H)")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # ==================================================================
    # 工具栏
    # ==================================================================
    def _setup_toolbar(self):
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.open_folder_btn = QPushButton("📂 打开文件夹")
        self.open_folder_btn.setToolTip("选择工作目录，左侧加载目录树")
        toolbar.addWidget(self.open_folder_btn)

        toolbar.addSeparator()
        self.work_dir_label = QLabel("当前工作目录: 未设置")
        self.work_dir_label.setStyleSheet("color: #0078d4; font-weight: bold;")
        toolbar.addWidget(self.work_dir_label)

    # ==================================================================
    # 中央区域 (三栏分割器)
    # ==================================================================
    def _setup_central_widget(self):
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        # ----- 左侧：文件树 (QTreeWidget) -----
        tree_container = QFrame()
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(4, 4, 4, 4)
        tree_layout.addWidget(QLabel("<b>文件目录树</b>"))

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setAnimated(True)
        self.tree.setIndentation(20)
        self.tree.setExpandsOnDoubleClick(False)   # 手动控制展开
        tree_layout.addWidget(self.tree)
        splitter.addWidget(tree_container)

        # ----- 中间：编排列表 + 操作按钮 -----
        middle_container = QFrame()
        middle_layout = QVBoxLayout(middle_container)
        middle_layout.setContentsMargins(4, 4, 4, 4)

        middle_layout.addWidget(QLabel("<b>输出编排列表</b> (顺序决定最终输出)"))

        # 列表控件 (支持内部拖拽排序)
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.MoveAction)
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        middle_layout.addWidget(self.list_widget)

        # 按钮行1
        btn_row1 = QHBoxLayout()
        btn_row1.addWidget(QPushButton("添加外部文件"))
        btn_row1.addWidget(QPushButton("插入文字 ↑"))
        btn_row1.addWidget(QPushButton("插入文字 ↓"))
        middle_layout.addLayout(btn_row1)

        # 按钮行2
        btn_row2 = QHBoxLayout()
        btn_row2.addWidget(QPushButton("上移"))
        btn_row2.addWidget(QPushButton("下移"))
        btn_row2.addWidget(QPushButton("删除"))
        btn_row2.addWidget(QPushButton("清空"))
        middle_layout.addLayout(btn_row2)

        # 路径模式选项
        opt_frame = QFrame()
        opt_layout = QHBoxLayout(opt_frame)
        opt_layout.setContentsMargins(0, 4, 0, 4)

        self.radio_rel = QRadioButton("相对路径")
        self.radio_abs = QRadioButton("绝对路径")
        self.path_mode_group = QButtonGroup()
        self.path_mode_group.addButton(self.radio_rel)
        self.path_mode_group.addButton(self.radio_abs)
        self.radio_rel.setChecked(True)
        opt_layout.addWidget(self.radio_rel)
        opt_layout.addWidget(self.radio_abs)

        self.check_header = QCheckBox("在文件头部标注工作目录绝对路径")
        opt_layout.addWidget(self.check_header)
        opt_layout.addStretch()
        middle_layout.addWidget(opt_frame)

        # 生成/保存按钮行
        btn_row3 = QHBoxLayout()
        btn_row3.addWidget(QPushButton("📄 生成 TXT"))
        btn_row3.addWidget(QPushButton("💾 保存项目"))
        btn_row3.addWidget(QPushButton("📂 加载项目"))
        middle_layout.addLayout(btn_row3)

        splitter.addWidget(middle_container)

        # ----- 右侧：预览区 -----
        preview_container = QFrame()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(4, 4, 4, 4)
        preview_layout.addWidget(QLabel("<b>预览区</b>"))

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setStyleSheet("background-color: #f5f5f5;")
        preview_layout.addWidget(self.preview)
        splitter.addWidget(preview_container)

        # 设置分割比例
        splitter.setStretchFactor(0, 2)  # 树
        splitter.setStretchFactor(1, 3)  # 列表+按钮
        splitter.setStretchFactor(2, 2)  # 预览

        # ---- 连接按钮信号 ----
        # 按钮需要在 _connect_signals 中统一连接，这里先拿到引用，后面连接
        self.btn_add_external = btn_row1.itemAt(0).widget()
        self.btn_insert_above = btn_row1.itemAt(1).widget()
        self.btn_insert_below = btn_row1.itemAt(2).widget()
        self.btn_move_up = btn_row2.itemAt(0).widget()
        self.btn_move_down = btn_row2.itemAt(1).widget()
        self.btn_delete = btn_row2.itemAt(2).widget()
        self.btn_clear = btn_row2.itemAt(3).widget()
        self.btn_generate = btn_row3.itemAt(0).widget()
        self.btn_save = btn_row3.itemAt(1).widget()
        self.btn_load = btn_row3.itemAt(2).widget()

    # ==================================================================
    # 状态栏
    # ==================================================================
    def _setup_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    # ==================================================================
    # 信号连接
    # ==================================================================
    def _connect_signals(self):
        # 工具栏
        self.open_folder_btn.clicked.connect(self.open_folder)

        # 中间按钮
        self.btn_add_external.clicked.connect(self.add_external_files)
        self.btn_insert_above.clicked.connect(
            lambda: self.insert_text(above=True))
        self.btn_insert_below.clicked.connect(
            lambda: self.insert_text(above=False))
        self.btn_move_up.clicked.connect(self.move_up)
        self.btn_move_down.clicked.connect(self.move_down)
        self.btn_delete.clicked.connect(self.delete_item)
        self.btn_clear.clicked.connect(self.clear_items)
        self.btn_generate.clicked.connect(self.generate_txt)
        self.btn_save.clicked.connect(self.save_project)
        self.btn_load.clicked.connect(self.load_project)

        # 单选按钮 / 复选框
        self.radio_rel.toggled.connect(self._on_path_mode_changed)
        self.check_header.stateChanged.connect(self._on_header_check_changed)

        # 树事件
        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        self.tree.itemExpanded.connect(self._on_tree_item_expanded)

        # 列表事件
        self.list_widget.currentItemChanged.connect(
            self._on_list_selection_changed)
        self.list_widget.itemDoubleClicked.connect(
            self._on_list_item_double_clicked)

        # 拖放外部文件到列表（需要重写事件）
        self.list_widget.setAcceptDrops(True)
        # 我们会重写 dragEnterEvent 和 dropEvent，但为了保持代码整洁，用事件过滤器或子类化
        # 这里采用替换方式：安装事件过滤器
        self.list_widget.installEventFilter(self)

    # ==================================================================
    # 事件过滤器（处理列表拖入外部文件）
    # ==================================================================
    def eventFilter(self, obj, event):
        if obj is self.list_widget:
            if event.type() == QDragEnterEvent.Type:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
                return False
            elif event.type() == QDropEvent.Type:
                urls = event.mimeData().urls()
                for url in urls:
                    file_path = url.toLocalFile()
                    if os.path.isfile(file_path):
                        self._add_file_to_items(file_path, force_absolute=True)
                self._refresh_list()
                return True
        return super().eventFilter(obj, event)

    # ==================================================================
    # 树状目录构建与懒加载
    # ==================================================================
    def _refresh_tree(self):
        """清空树并根据 work_dir 构建根节点（只加载第一层）"""
        self.tree.clear()
        self.checked_paths.clear()
        self.tree_loading_dirs.clear()

        if self.work_dir and self.work_dir.exists():
            root = QTreeWidgetItem(self.tree)
            root.setText(0, self.work_dir.name)
            root.setData(0, Qt.UserRole, str(self.work_dir))  # 存储路径
            root.setFlags(root.flags() & ~Qt.ItemIsUserCheckable)  # 根节点不可勾选
            self._insert_children(root, self.work_dir)
            self.tree_loading_dirs.add(str(self.work_dir))
            root.setExpanded(True)

    def _insert_children(self, parent_item, dir_path: Path):
        """在指定节点下插入直接子项（不递归），文件夹添加虚拟子节点以支持展开"""
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (
                not p.is_dir(), p.name.lower()))
        except PermissionError:
            return

        for entry in entries:
            if entry.name.startswith('.') and entry.is_dir():
                continue
            if entry.is_dir():
                if entry.name in self.ignore_dirs:
                    continue
                item = QTreeWidgetItem(parent_item)
                item.setText(0, entry.name)
                item.setData(0, Qt.UserRole, str(entry))
                # 文件夹不参与勾选，但可以展开
                item.setFlags(item.flags() | Qt.ItemIsAutoTristate)
                # 插入一个虚拟子节点，使其可以展开
                dummy = QTreeWidgetItem(item)
                dummy.setText(0, "")
            else:
                item = QTreeWidgetItem(parent_item)
                item.setText(0, entry.name)
                item.setData(0, Qt.UserRole, str(entry))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Unchecked)

    def _on_tree_item_expanded(self, item):
        """懒加载：目录展开时动态加载子节点"""
        dir_path = item.data(0, Qt.UserRole)
        if not dir_path:
            return
        p = Path(dir_path)
        if not p.is_dir() or str(p) in self.tree_loading_dirs:
            return

        # 移除虚拟子节点
        while item.childCount() == 1 and item.child(0).text(0) == "":
            item.removeChild(item.child(0))

        # 真正加载子项
        self._insert_children(item, p)
        self.tree_loading_dirs.add(str(p))

    def _on_tree_item_clicked(self, item, column):
        """处理文件勾选切换"""
        if item.flags() & Qt.ItemIsUserCheckable:
            path_str = item.data(0, Qt.UserRole)
            if not path_str:
                return
            checked = item.checkState(0) == Qt.Checked
            if checked:
                if path_str not in self.checked_paths:
                    self.checked_paths.add(path_str)
                    self._add_file_to_items(path_str, force_absolute=False)
            else:
                if path_str in self.checked_paths:
                    self.checked_paths.remove(path_str)
                    self._remove_items_by_path(path_str)
            self._refresh_list()
            self.status_bar.showMessage(f"已勾选 {len(self.checked_paths)} 个文件")

    # ==================================================================
    # 编排列表管理
    # ==================================================================
    def _add_file_to_items(self, abs_path_str, force_absolute):
        """将文件添加到编排列表末尾"""
        item_data = ItemData(
            type_="file",
            path=abs_path_str,
            force_absolute=force_absolute
        )
        self.items.append(item_data)

    def _remove_items_by_path(self, abs_path_str):
        """移除列表中所有匹配路径的文件条目"""
        self.items = [it for it in self.items if not (
            it.type == "file" and it.path == abs_path_str)]

    def _refresh_list(self):
        """根据 self.items 刷新 QListWidget"""
        self.list_widget.clear()
        for data in self.items:
            display = self._get_display_text(data)
            lw_item = QListWidgetItem(display)
            lw_item.setData(Qt.UserRole, data)
            self.list_widget.addItem(lw_item)

    def _get_display_text(self, data: ItemData) -> str:
        """根据条目生成列表显示文本"""
        if data.type == "file":
            p = Path(data.path)
            if data.force_absolute:
                return f"📌 {p.name} (绝对路径)"
            else:
                mode = "(相对)" if not self.use_absolute else "(绝对)"
                return f"📄 {p.name} {mode}"
        else:  # text
            preview = data.content[:30] + \
                ('...' if len(data.content) > 30 else '')
            return f"📝 {preview}"

    def add_external_files(self):
        """手动添加外部文件（强制绝对路径）"""
        files, _ = QFileDialog.getOpenFileNames(self, "选择外部文件")
        if files:
            for f in files:
                abs_path = str(Path(f).resolve())
                self._add_file_to_items(abs_path, force_absolute=True)
            self._refresh_list()
            self.status_bar.showMessage(f"已添加 {len(files)} 个外部文件")

    def insert_text(self, above=True):
        """在选中条目前/后插入自定义文字"""
        current_row = self.list_widget.currentRow()
        if current_row == -1:
            index = len(self.items) if above else len(self.items)
        else:
            index = current_row if above else current_row + 1

        dialog = TextEditDialog(self, "插入自定义文字")
        if dialog.exec() == QDialog.Accepted:
            text = dialog.get_text()
            if text:
                item_data = ItemData(type_="text", content=text)
                self.items.insert(index, item_data)
                self._refresh_list()
                self.list_widget.setCurrentRow(index)
                self.status_bar.showMessage("已插入文字")

    def move_up(self):
        row = self.list_widget.currentRow()
        if row > 0:
            self.items[row], self.items[row -
                                        1] = self.items[row-1], self.items[row]
            self._refresh_list()
            self.list_widget.setCurrentRow(row-1)

    def move_down(self):
        row = self.list_widget.currentRow()
        if row < len(self.items) - 1:
            self.items[row], self.items[row +
                                        1] = self.items[row+1], self.items[row]
            self._refresh_list()
            self.list_widget.setCurrentRow(row+1)

    def delete_item(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            data = self.items[row]
            # 如果是树内文件且未强制绝对路径，同步取消树勾选
            if data.type == "file" and not data.force_absolute:
                if data.path in self.checked_paths:
                    self.checked_paths.remove(data.path)
                    # 在树中查找并取消勾选
                    self._set_tree_item_check(data.path, Qt.Unchecked)
            del self.items[row]
            self._refresh_list()
            self.status_bar.showMessage("条目已删除")

    def clear_items(self):
        reply = QMessageBox.question(self, "确认", "确定清空编排列表吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            # 取消所有树勾选
            for path in list(self.checked_paths):
                self._set_tree_item_check(path, Qt.Unchecked)
            self.checked_paths.clear()
            self.items.clear()
            self._refresh_list()
            self.status_bar.showMessage("编排列表已清空")

    def _set_tree_item_check(self, abs_path, state):
        """在树中递归查找路径并设置勾选状态"""
        def search(item):
            if item.flags() & Qt.ItemIsUserCheckable:
                if item.data(0, Qt.UserRole) == abs_path:
                    item.setCheckState(0, state)
                    return True
            for i in range(item.childCount()):
                if search(item.child(i)):
                    return True
            return False

        for i in range(self.tree.topLevelItemCount()):
            search(self.tree.topLevelItem(i))

    # ==================================================================
    # 列表交互事件
    # ==================================================================
    def _on_list_selection_changed(self, current, previous):
        """选中条目时更新预览"""
        if current is None:
            self.preview.clear()
            return
        data = current.data(Qt.UserRole)
        if not isinstance(data, ItemData):
            return
        self._show_preview(data)

    def _on_list_item_double_clicked(self, item):
        """双击编辑文字条目"""
        data = item.data(Qt.UserRole)
        if isinstance(data, ItemData) and data.type == "text":
            dialog = TextEditDialog(self, "编辑文字", initial_text=data.content)
            if dialog.exec() == QDialog.Accepted:
                new_text = dialog.get_text()
                if new_text:
                    data.content = new_text
                    self._refresh_list()
                    self.list_widget.setCurrentRow(
                        self.list_widget.currentRow())  # 保持不变
                    self._show_preview(data)
                    self.status_bar.showMessage("文字已更新")

    # 内部拖拽排序后同步 self.items 顺序（QListWidget InternalMove 会自动重排列表项，但数据没变）
    # 我们需要在拖拽完成后更新 self.items
    def _sync_items_from_list(self):
        """从 list_widget 中按顺序读取 ItemData 重建 self.items"""
        new_items = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            data = item.data(Qt.UserRole)
            if isinstance(data, ItemData):
                new_items.append(data)
        self.items = new_items

    # 通过重写 list_widget 的 dropEvent 来同步，最简单的是连接 model 信号，但这里我们可以在每次可能拖拽后调用
    # 更稳健：监听 QListWidget 的 model 的 rowsInserted 等，简单起见，在关键操作后调用同步
    # 我们将在 dropEvent 被调用后同步，但因为我们用了事件过滤器，可以在 dropEvent 后触发
    # 采用定时器或直接重新实现 dropEvent。由于复杂度，我们提供按钮操作时手动同步，
    # 但为了让拖拽排序自动生效，我们重写 list_widget 的 dropEvent：
    # 我们可以在初始化后替换 list_widget 的 dropEvent 方法，但比较 hack。
    # 更简单：连接 list_widget.model().rowsMoved 信号。
    # 这里我们采用信号方式：
    # 在 _connect_signals 中增加：
    # self.list_widget.model().rowsMoved.connect(self._on_rows_moved)
    # 但这要求 QListWidget 的内部 model 是 QStandardItemModel，是的。

    def _on_rows_moved(self, parent, start, end, destination, row):
        """列表内部拖拽排序后，同步数据"""
        self._sync_items_from_list()

    # 在 _connect_signals 中增加以下连接：
    # self.list_widget.model().rowsMoved.connect(self._on_rows_moved)
    # 我们在 _connect_signals 末尾添加

    # ==================================================================
    # 预览区
    # ==================================================================
    def _show_preview(self, data: ItemData):
        self.preview.clear()
        if data.type == "file":
            if not os.path.exists(data.path):
                self.preview.setPlainText("[文件不存在]")
                return
            try:
                content, enc = safe_read_file(data.path, max_preview_lines=50)
                preview_text = f"--- 文件预览 (编码: {enc}) ---\n{content}"
                self.preview.setPlainText(preview_text)
            except Exception as e:
                self.preview.setPlainText(f"[读取错误: {e}]")
        else:
            self.preview.setPlainText(data.content)

    # ==================================================================
    # 路径模式切换
    # ==================================================================
    def _on_path_mode_changed(self, checked):
        if self.radio_abs.isChecked():
            self.use_absolute = True
            self.check_header.setEnabled(False)
            self.check_header.setChecked(False)
        else:
            self.use_absolute = False
            self.check_header.setEnabled(True)
        self._update_path_mode_ui()

    def _on_header_check_changed(self, state):
        self.show_header = (state == Qt.Checked)

    def _update_path_mode_ui(self):
        """路径模式变化后刷新列表显示标签"""
        self._refresh_list()

    # ==================================================================
    # 生成 TXT
    # ==================================================================
    def generate_txt(self):
        if not self.items:
            QMessageBox.warning(self, "警告", "编排列表为空，无法生成。")
            return

        file_path, _ = QFileDialog.getSaveFileName(self, "保存合并文本", "",
                                                   "Text files (*.txt);;All files (*)")
        if not file_path:
            return

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                # 头部注释
                if not self.use_absolute and self.show_header and self.work_dir:
                    f.write(f"# 工作目录绝对路径: {self.work_dir}\n\n")

                for i, data in enumerate(self.items):
                    if i > 0:
                        f.write("\n\n")
                    if data.type == "file":
                        file_p = Path(data.path)
                        if not file_p.exists():
                            f.write(f"[文件不存在: {data.path}]\n")
                            continue
                        # 确定显示路径
                        if data.force_absolute or self.use_absolute or not self.work_dir:
                            display = str(file_p.resolve())
                        else:
                            try:
                                display = str(
                                    file_p.resolve().relative_to(self.work_dir))
                            except ValueError:
                                display = str(file_p.resolve())
                        f.write(f"{display}:\n")
                        try:
                            content, _ = safe_read_file(data.path)
                            f.write(content)
                        except Exception as e:
                            f.write(f"[读取错误: {e}]")
                    else:
                        f.write(data.content)

            self.status_bar.showMessage(f"TXT 已生成: {file_path}")
            QMessageBox.information(self, "成功", f"文件已保存到:\n{file_path}")

            # 询问打开位置
            reply = QMessageBox.question(self, "打开位置", "是否打开文件所在文件夹？",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self._open_file_location(file_path)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成 TXT 失败:\n{e}")

    def _open_file_location(self, path):
        """跨平台打开文件所在文件夹并选中文件"""
        try:
            import subprocess
            if sys.platform == "win32":
                subprocess.Popen(
                    ['explorer', '/select,', path.replace('/', '\\')])
            elif sys.platform == "darwin":
                subprocess.Popen(['open', '-R', path])
            else:
                subprocess.Popen(['xdg-open', os.path.dirname(path)])
        except Exception:
            pass

    # ==================================================================
    # 打开文件夹
    # ==================================================================
    def open_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "选择工作文件夹")
        if directory:
            self.work_dir = Path(directory).resolve()
            self.work_dir_label.setText(f"当前工作目录: {self.work_dir}")
            self._refresh_tree()
            # 保持已存在的编排列表不变，但相对路径可能受影响，刷新显示
            self._refresh_list()
            self.status_bar.showMessage(f"已设置工作目录: {self.work_dir}")

    # ==================================================================
    # 项目保存与加载
    # ==================================================================
    def save_project(self):
        if not self.project_file:
            return self.save_project_as()
        self._write_project(self.project_file)

    def save_project_as(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "保存项目", "",
                                                   "Project JSON (*.project.json)")
        if file_path:
            self.project_file = file_path
            self._write_project(file_path)

    def _write_project(self, file_path):
        try:
            data = {
                "work_dir": str(self.work_dir) if self.work_dir else None,
                "use_absolute": self.use_absolute,
                "show_header": self.show_header,
                "checked_files": list(self.checked_paths),
                "items": []
            }
            for item_data in self.items:
                if item_data.type == "file":
                    data["items"].append({
                        "type": "file",
                        "path": item_data.path,
                        "force_absolute": item_data.force_absolute
                    })
                else:
                    data["items"].append({
                        "type": "text",
                        "content": item_data.content
                    })

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.project_file = file_path
            self.status_bar.showMessage(f"项目已保存: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def load_project(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "打开项目", "",
                                                   "Project JSON (*.project.json)")
        if not file_path:
            return
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 工作目录
            wd = data.get("work_dir")
            if wd and Path(wd).exists():
                self.work_dir = Path(wd).resolve()
                self.work_dir_label.setText(f"当前工作目录: {self.work_dir}")
            else:
                self.work_dir = None
                self.work_dir_label.setText("当前工作目录: 未设置")

            self._refresh_tree()

            # 恢复勾选
            checked_files = set(data.get("checked_files", []))
            self.checked_paths.clear()
            for p_str in checked_files:
                if os.path.exists(p_str):
                    self.checked_paths.add(p_str)
                    self._set_tree_item_check(p_str, Qt.Checked)

            # 路径选项
            self.use_absolute = data.get("use_absolute", False)
            self.show_header = data.get("show_header", False)
            self.radio_abs.setChecked(self.use_absolute)
            self.radio_rel.setChecked(not self.use_absolute)
            self.check_header.setChecked(self.show_header)
            self._update_path_mode_ui()

            # 编排列表
            self.items.clear()
            for item_dict in data.get("items", []):
                if item_dict["type"] == "file":
                    p = item_dict["path"]
                    if not os.path.exists(p):
                        # 文件缺失，插入文字提示
                        it = ItemData("text", content=f"[缺失文件: {p}]")
                    else:
                        it = ItemData("file", path=p, force_absolute=item_dict.get(
                            "force_absolute", False))
                    self.items.append(it)
                else:
                    self.items.append(
                        ItemData("text", content=item_dict["content"]))
            self._refresh_list()

            self.project_file = file_path
            self.status_bar.showMessage(f"项目已加载: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"项目文件损坏或格式不正确:\n{e}")
            traceback.print_exc()

    # ==================================================================
    # 其他
    # ==================================================================
    def _show_about(self):
        QMessageBox.about(self, "关于 FileCollector",
                          "文件收集与编排工具 v2.0 (PySide6)\n"
                          "跨平台支持 Windows / macOS / Linux\n"
                          "高清屏适配，现代字体渲染\n\n"
                          "功能：目录树勾选、拖放排序、文字编排、编码检测、项目保存")

    def closeEvent(self, event):
        if self.items:
            reply = QMessageBox.question(self, "确认退出", "编排列表不为空，确定退出吗？",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                event.ignore()
                return
        event.accept()


# ======================================================================
# 程序入口
# ======================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # 统一风格，高分屏友好
    window = FileCollectorApp()
    window.show()
    sys.exit(app.exec())
