import os
import queue
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer, QMimeData, QUrl
from PySide6.QtGui import QAction, QFont, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMenuBar, QMenu, QToolBar, QStatusBar,
    QSplitter, QTreeWidget, QTreeWidgetItem, QListWidget, QListWidgetItem,
    QTextEdit, QPushButton, QRadioButton, QCheckBox, QLabel, QVBoxLayout,
    QHBoxLayout, QWidget, QFileDialog, QMessageBox, QButtonGroup, QFrame, QDialog,
    QLineEdit
)

from filecollector.models import ItemData
from filecollector.engine import FileCollectorEngine
from filecollector.utils import safe_read_file
from filecollector.gui.dialogs import TextEditDialog
from filecollector.gui.undo import UndoState, UndoManager
from filecollector.gui.gui_actions import (
    generate_txt as _generate_txt,
    generate_to_clipboard as _generate_to_clipboard,
    open_folder as _open_folder,
    save_project as _save_project,
    save_project_as as _save_project_as,
    load_project as _load_project,
    show_about as _show_about,
)
from filecollector.gui.toast import ToastNotification


class FileCollectorApp(QMainWindow):
    status_message = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FileCollector - 文件收集与编排工具")
        self.resize(1300, 780)
        self.setMinimumSize(950, 500)

        self.engine = FileCollectorEngine()

        self.undo_manager = UndoManager()
        self.tree_loading_dirs = set()
        self.ignore_dirs = {'.git', 'node_modules', '__pycache__',
                            '.svn', '.hg', 'venv', '.idea', '.vscode'}
        self.common_phrases = (list(self.engine.common_phrases) if hasattr(self.engine, "common_phrases") else [])
        if not self.common_phrases and hasattr(self.engine, "load_common_phrases_from_disk"):
            self.common_phrases = self.engine.load_common_phrases_from_disk()

        font = QFont()
        font.setPointSize(10)
        QApplication.setFont(font)

        self._setup_menu_bar()
        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_status_bar()
        self._connect_signals()

        self._refresh_tree()

        # IPC server: receive CLI commands from other instances
        self.ipc_queue = queue.Queue()
        self.ipc_stop = None
        self._start_ipc_server()

    # ------------------------------------------------------------------
    # IPC: single-instance communication
    # ------------------------------------------------------------------
    def _start_ipc_server(self):
        from filecollector.ipc import start_ipc_server

        self.ipc_stop = start_ipc_server(self.ipc_queue.put)

        self.ipc_timer = QTimer(self)
        self.ipc_timer.timeout.connect(self._process_ipc_queue)
        self.ipc_timer.start(100)

    def _process_ipc_queue(self):
        while not self.ipc_queue.empty():
            try:
                args = self.ipc_queue.get_nowait()
                self._handle_ipc_args(args)
            except queue.Empty:
                break

    def _handle_ipc_args(self, args):
        """Apply CLI args received from another process to this instance."""
        from filecollector.cli import apply_cli_args

        if apply_cli_args(self.engine, args, print_feedback=False):
            self.initialize_from_engine(self.engine)
            self.status_bar.showMessage(
                f"已从外部命令更新 ({len(self.engine.items)} 项)"
            )
        else:
            self.status_bar.showMessage("外部命令解析失败")

    def initialize_from_engine(self, engine):
        """Initialize GUI state from a pre-configured engine (used by CLI --gui)."""
        self.engine = engine

        if self.engine.work_dir:
            self.work_dir_label.setText(f"当前工作目录: {self.engine.work_dir}")
        else:
            self.work_dir_label.setText("当前工作目录: 未设置")

        self._refresh_tree()

        for p_str in self.engine.checked_paths:
            self._set_tree_item_check(p_str, Qt.Checked)

        self.radio_abs.setChecked(self.engine.use_absolute)
        self.radio_rel.setChecked(not self.engine.use_absolute)
        self.check_header.setChecked(self.engine.show_header)
        self._update_path_mode_ui()

        self._refresh_list()

        self.status_bar.showMessage(f"已从 CLI 参数加载 {len(self.engine.items)} 个项目")

    # ==================================================================
    # 菜单栏
    # ==================================================================
    def _setup_menu_bar(self):
        menu_bar = self.menuBar()

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

        settings_menu = menu_bar.addMenu("设置(&S)")
        lang_action = QAction("语言设置...", self)
        lang_action.setShortcut("Ctrl+,")
        lang_action.triggered.connect(self._open_settings)
        settings_menu.addAction(lang_action)
        phrases_action = QAction("常用语管理(&M)", self)
        phrases_action.triggered.connect(self._open_phrases_manager)
        settings_menu.addAction(phrases_action)

        help_menu = menu_bar.addMenu("帮助(&H)")
        shortcuts_action = QAction("键盘快捷键", self)
        shortcuts_action.setShortcut("Ctrl+/")
        shortcuts_action.triggered.connect(self._open_shortcuts)
        help_menu.addAction(shortcuts_action)
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

        self.btn_undo = QPushButton("↶ 撤销")
        self.btn_undo.setToolTip("撤销 (Ctrl+Z)")
        self.btn_undo.setEnabled(False)
        toolbar.addWidget(self.btn_undo)

        self.btn_redo = QPushButton("↷ 重做")
        self.btn_redo.setToolTip("重做 (Ctrl+Shift+Z)")
        self.btn_redo.setEnabled(False)
        toolbar.addWidget(self.btn_redo)

        toolbar.addSeparator()

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

        tree_container = QFrame()
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(4, 4, 4, 4)
        tree_layout.addWidget(QLabel("<b>文件目录树</b>"))

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_tree_search_changed)
        self.search_input.setVisible(False)
        tree_layout.addWidget(self.search_input)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setAnimated(True)
        self.tree.setIndentation(20)
        self.tree.setExpandsOnDoubleClick(False)
        tree_layout.addWidget(self.tree)
        splitter.addWidget(tree_container)

        middle_container = QFrame()
        middle_layout = QVBoxLayout(middle_container)
        middle_layout.setContentsMargins(4, 4, 4, 4)
        middle_layout.addWidget(QLabel("<b>输出编排列表</b> (顺序决定最终输出)"))

        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.MoveAction)
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        middle_layout.addWidget(self.list_widget)

        btn_row1 = QHBoxLayout()
        btn_row1.addWidget(QPushButton("添加外部文件"))
        btn_row1.addWidget(QPushButton("插入文字 ↑"))
        btn_row1.addWidget(QPushButton("插入文字 ↓"))
        middle_layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        btn_row2.addWidget(QPushButton("上移"))
        btn_row2.addWidget(QPushButton("下移"))
        btn_row2.addWidget(QPushButton("删除"))
        btn_row2.addWidget(QPushButton("清空"))
        middle_layout.addLayout(btn_row2)

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

        btn_row3 = QHBoxLayout()
        btn_row3.addWidget(QPushButton("📄 生成 TXT"))
        btn_row3.addWidget(QPushButton("📋 生成到剪贴板"))
        btn_row3.addWidget(QPushButton("💾 保存项目"))
        btn_row3.addWidget(QPushButton("📂 加载项目"))
        middle_layout.addLayout(btn_row3)

        splitter.addWidget(middle_container)

        preview_container = QFrame()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(4, 4, 4, 4)
        preview_layout.addWidget(QLabel("<b>预览区</b>"))

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setStyleSheet("background-color: #f5f5f5;")
        preview_layout.addWidget(self.preview)
        splitter.addWidget(preview_container)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)

        self.btn_add_external = btn_row1.itemAt(0).widget()
        self.btn_insert_above = btn_row1.itemAt(1).widget()
        self.btn_insert_below = btn_row1.itemAt(2).widget()
        self.btn_move_up = btn_row2.itemAt(0).widget()
        self.btn_move_down = btn_row2.itemAt(1).widget()
        self.btn_delete = btn_row2.itemAt(2).widget()
        self.btn_clear = btn_row2.itemAt(3).widget()
        self.btn_generate = btn_row3.itemAt(0).widget()
        self.btn_generate_clipboard = btn_row3.itemAt(1).widget()
        self.btn_save = btn_row3.itemAt(2).widget()
        self.btn_load = btn_row3.itemAt(3).widget()

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
        self.open_folder_btn.clicked.connect(self.open_folder)

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

        self.radio_rel.toggled.connect(self._on_path_mode_changed)
        self.check_header.stateChanged.connect(self._on_header_check_changed)

        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        self.tree.itemExpanded.connect(self._on_tree_item_expanded)

        self.list_widget.currentItemChanged.connect(
            self._on_list_selection_changed)
        self.list_widget.itemDoubleClicked.connect(
            self._on_list_item_double_clicked)

        self.list_widget.setAcceptDrops(True)
        self.list_widget.installEventFilter(self)
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)

    # ==================================================================
    # 事件过滤器
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
                        self.engine.add_file(file_path, force_absolute=True)
                self._refresh_list()
                return True
        return super().eventFilter(obj, event)

    # ==================================================================
    # 树状目录
    # ==================================================================
    def _refresh_tree(self):
        self.tree.clear()
        self.tree_loading_dirs.clear()

        if self.engine.work_dir and self.engine.work_dir.exists():
            root = QTreeWidgetItem(self.tree)
            root.setText(0, self.engine.work_dir.name)
            root.setData(0, Qt.UserRole, str(self.engine.work_dir))
            root.setFlags(root.flags() & ~Qt.ItemIsUserCheckable)
            self._insert_children(root, self.engine.work_dir)
            self.tree_loading_dirs.add(str(self.engine.work_dir))
            root.setExpanded(True)

    def _insert_children(self, parent_item, dir_path: Path):
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
                item.setFlags(item.flags() | Qt.ItemIsAutoTristate)
                dummy = QTreeWidgetItem(item)
                dummy.setText(0, "")
            else:
                item = QTreeWidgetItem(parent_item)
                item.setText(0, entry.name)
                item.setData(0, Qt.UserRole, str(entry))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Unchecked)

    def _on_tree_item_expanded(self, item):
        dir_path = item.data(0, Qt.UserRole)
        if not dir_path:
            return
        p = Path(dir_path)
        if not p.is_dir() or str(p) in self.tree_loading_dirs:
            return

        while item.childCount() == 1 and item.child(0).text(0) == "":
            item.removeChild(item.child(0))

        self._insert_children(item, p)
        self.tree_loading_dirs.add(str(p))

    def _on_tree_item_clicked(self, item, column):
        if item.flags() & Qt.ItemIsUserCheckable:
            path_str = item.data(0, Qt.UserRole)
            if not path_str:
                return
            checked = item.checkState(0) == Qt.Checked
            if checked:
                if path_str not in self.engine.checked_paths:
                    self.engine.checked_paths.add(path_str)
                    self.engine.add_file(path_str, force_absolute=False)
            else:
                if path_str in self.engine.checked_paths:
                    self.engine.checked_paths.remove(path_str)
                    self.engine.remove_items_by_path(path_str)
        else:
            p = Path(item.data(0, Qt.UserRole) or "")
            if not p.exists():
                return
            state = item.checkState(0)
            new_state = Qt.Unchecked if state == Qt.Checked else Qt.Checked
            self._apply_dir_check_state(item, new_state)
        self._refresh_list()
        self._update_tree_ancestors()
        self.status_bar.showMessage(f"已勾选 {len(self.engine.checked_paths)} 个文件")

    def _apply_dir_check_state(self, item, state):
        for i in range(item.childCount()):
            child = item.child(i)
            if child.flags() & Qt.ItemIsUserCheckable:
                child.setCheckState(0, state)
                path_str = child.data(0, Qt.UserRole)
                if path_str:
                    if state == Qt.Checked:
                        self.engine.checked_paths.add(path_str)
                    else:
                        self.engine.checked_paths.discard(path_str)
                        self.engine.remove_items_by_path(path_str)
            if child.childCount():
                self._apply_dir_check_state(child, state)

    def _update_tree_ancestors(self):
        for i in range(self.tree.topLevelItemCount()):
            self._refresh_item_state(self.tree.topLevelItem(i))

    def _refresh_item_state(self, item):
        if item.childCount():
            total = 0
            checked = 0
            inconsistent = False
            for i in range(item.childCount()):
                child = item.child(i)
                if child.flags() & Qt.ItemIsUserCheckable:
                    total += 1
                    cs = child.checkState(0)
                    if cs == Qt.Checked:
                        checked += 1
                    elif cs == Qt.PartiallyChecked:
                        inconsistent = True
                else:
                    self._refresh_item_state(child)
                    total += 1
                    checked += child.checkState(0) == Qt.Checked
                    inconsistent = inconsistent or child.checkState(0) == Qt.PartiallyChecked
            if total == 0:
                item.setCheckState(0, Qt.Unchecked)
            elif inconsistent:
                item.setCheckState(0, Qt.PartiallyChecked)
            elif checked == total:
                item.setCheckState(0, Qt.Checked)
            else:
                item.setCheckState(0, Qt.Unchecked)

    def _restore_tree_checks(self, checked_paths):
        def walk(item):
            if item.flags() & Qt.ItemIsUserCheckable:
                path_str = item.data(0, Qt.UserRole)
                if path_str:
                    item.setCheckState(0, Qt.Checked if path_str in checked_paths else Qt.Unchecked)
            for i in range(item.childCount()):
                walk(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    # ==================================================================
    # 编排列表
    # ==================================================================
    def _refresh_list(self):
        self.list_widget.clear()
        for data in self.engine.items:
            display = self._get_display_text(data)
            lw_item = QListWidgetItem(display)
            lw_item.setData(Qt.UserRole, data)
            self.list_widget.addItem(lw_item)

    def _get_display_text(self, data: ItemData) -> str:
        if data.type == "file":
            p = Path(data.path)
            if data.force_absolute:
                return f"📌 {p.name} (绝对路径)"
            else:
                mode = "(相对)" if not self.engine.use_absolute else "(绝对)"
                return f"📄 {p.name} {mode}"
        else:
            preview = data.content[:30] + \
                ('...' if len(data.content) > 30 else '')
            return f"📝 {preview}"

    def add_external_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择外部文件")
        if files:
            for f in files:
                abs_path = str(Path(f).resolve())
                self.engine.add_file(abs_path, force_absolute=True)
            self._refresh_list()
            self.status_bar.showMessage(f"已添加 {len(files)} 个外部文件")

    def move_up(self):
        row = self.list_widget.currentRow()
        if row > 0:
            self.engine.move_item(row, row - 1)
            self._refresh_list()
            self.list_widget.setCurrentRow(row - 1)

    def move_down(self):
        row = self.list_widget.currentRow()
        if row < len(self.engine.items) - 1:
            self.engine.move_item(row, row + 1)
            self._refresh_list()
            self.list_widget.setCurrentRow(row + 1)

    def delete_item(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            data = self.engine.items[row]
            if data.type == "file" and not data.force_absolute:
                if data.path in self.engine.checked_paths:
                    self.engine.checked_paths.remove(data.path)
                    self._set_tree_item_check(data.path, Qt.Unchecked)
            self.engine.remove_item(row)
            self._refresh_list()
            self.status_bar.showMessage("条目已删除")

    def clear_items(self):
        reply = QMessageBox.question(self, "确认", "确定清空编排列表吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            for path in list(self.engine.checked_paths):
                self._set_tree_item_check(path, Qt.Unchecked)
            self.engine.clear()
            self._refresh_list()
            self.status_bar.showMessage("编排列表已清空")

    def _set_tree_item_check(self, abs_path, state):
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
    # 列表交互
    # ==================================================================
    def _on_list_selection_changed(self, current, previous):
        if current is None:
            self.preview.clear()
            return
        data = current.data(Qt.UserRole)
        if not isinstance(data, ItemData):
            return
        self._show_preview(data)

    def _on_list_item_double_clicked(self, item):
        data = item.data(Qt.UserRole)
        if isinstance(data, ItemData) and data.type == "text":
            dialog = TextEditDialog(self, "编辑文字", initial_text=data.content)
            if dialog.exec() == QDialog.Accepted:
                new_text = dialog.get_text()
                if new_text:
                    data.content = new_text
                    self._refresh_list()
                    self.list_widget.setCurrentRow(
                        self.list_widget.currentRow())
                    self._show_preview(data)
                    self.status_bar.showMessage("文字已更新")

    def _sync_items_from_list(self):
        new_items = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            data = item.data(Qt.UserRole)
            if isinstance(data, ItemData):
                new_items.append(data)
        self.engine.items = new_items

    def _on_rows_moved(self, parent, start, end, destination, row):
        self._sync_items_from_list()

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
    # 路径模式
    # ==================================================================
    def _update_path_mode_ui(self):
        self.check_header.setEnabled(not self.engine.use_absolute)

    def _on_header_check_changed(self, state):
        self.engine.show_header = (state == Qt.Checked)

    def _on_path_mode_changed(self, checked):
        if not checked:
            return
        self._push_undo()
        self.engine.use_absolute = self.radio_abs.isChecked()
        self._update_path_mode_ui()

    # ==================================================================
    # 生成 TXT
    # ==================================================================
    def generate_txt(self):
        if not self.engine.items:
            QMessageBox.warning(self, "警告", "编排列表为空，无法生成。")
            return

        file_path, _ = QFileDialog.getSaveFileName(self, "保存合并文本", "",
                                                   "Text files (*.txt);;All files (*)")
        if not file_path:
            return
        if not file_path.lower().endswith('.txt'):
            file_path += '.txt'

        try:
            self.engine.export(file_path)

            self.status_bar.showMessage(f"TXT 已生成: {file_path}")
            ToastNotification.show_toast(
                f"文件已保存到:\n{file_path}", self, ToastNotification.DEFAULT_DURATION + 1000
            )
            self._open_file_location(file_path)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成 TXT 失败:\n{e}")

    def generate_to_clipboard(self):
        if not self.engine.items:
            QMessageBox.warning(self, "警告", "编排列表为空，无法生成。")
            return
        try:
            import subprocess
            from filecollector.config import get_merged_txt_path
            self.engine.export(get_merged_txt_path())
            if sys.platform == "win32":
                subprocess.run(["clip"], input=open(get_merged_txt_path(), "rb").read(), check=False)
            else:
                subprocess.run(["xclip", "-selection", "clipboard", get_merged_txt_path()], check=False)
            self.status_bar.showMessage("合并文本已复制到剪贴板")
            self._show_toast("合并文本已复制到剪贴板")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"复制到剪贴板失败:\n{e}")

    def _open_file_location(self, path):
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
            self.engine.work_dir = Path(directory).resolve()
            self.work_dir_label.setText(f"当前工作目录: {self.engine.work_dir}")
            self._refresh_tree()
            self._refresh_list()
            self.search_input.setVisible(True)
            self.status_bar.showMessage(f"已设置工作目录: {self.engine.work_dir}")

    # ==================================================================
    # 项目保存/加载
    # ==================================================================
    def save_project(self):
        if not self.engine.project_file:
            return self.save_project_as()
        self._write_project(self.engine.project_file)

    def save_project_as(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "保存项目", "",
                                                   "Project (*.project.json *.fcol *.fcol.json);;Project JSON (*.project.json);;GNOME Project (*.fcol *.fcol.json)",
                                                   selectedFilter="Project (*.project.json *.fcol *.fcol.json)")
        if file_path:
            if not (file_path.endswith(".project.json") or file_path.endswith(".fcol") or file_path.endswith(".fcol.json")):
                file_path += ".project.json"
            self._write_project(file_path)

    def _write_project(self, file_path):
        try:
            self.engine.common_phrases = list(self.common_phrases)
            self.engine.save_project(file_path)
            self.engine.project_file = file_path
            self.status_bar.showMessage(f"项目已保存: {file_path}")
            self._show_toast(f"项目已保存: {Path(file_path).name}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))

    def load_project(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "打开项目", "",
                                                   "Project (*.project.json *.fcol *.fcol.json);;Project JSON (*.project.json);;GNOME Project (*.fcol *.fcol.json)",
                                                   selectedFilter="Project (*.project.json *.fcol *.fcol.json)")
        if not file_path:
            return
        try:
            self.engine.load_project(file_path)
            self.work_dir_label.setText(f"当前工作目录: {self.engine.work_dir}" if self.engine.work_dir else "当前工作目录: 未设置")
            self._refresh_tree()
            self._restore_tree_checks(self.engine.checked_paths)
            self.radio_abs.setChecked(self.engine.use_absolute)
            self.radio_rel.setChecked(not self.engine.use_absolute)
            self.check_header.setChecked(self.engine.show_header)
            self._update_path_mode_ui()
            self._refresh_list()
            self.common_phrases = list(self.engine.common_phrases)
            self.engine.project_file = file_path
            self.status_bar.showMessage(f"项目已加载: {file_path}")
            self._show_toast(f"项目已加载: {Path(file_path).name}")
        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"项目文件损坏或格式不正确:\n{e}")
            traceback.print_exc()

    def _show_about(self):
        from filecollector.gui.gui_actions import show_about as _show_about
        _show_about(self)


    def closeEvent(self, event):
        if self.ipc_stop:
            self.ipc_stop()
        if self.engine.items:
            reply = QMessageBox.question(self, "确认退出", "编排列表不为空，确定退出吗？",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                event.ignore()
                return
        event.accept()

    def _push_undo(self):
        self.undo_manager.push(UndoState(
            self.engine.items,
            self.engine.checked_paths,
            self.engine.use_absolute,
            self.engine.show_header,
        ))

    def on_undo(self):
        state = self.undo_manager.undo(UndoState(
            self.engine.items,
            self.engine.checked_paths,
            self.engine.use_absolute,
            self.engine.show_header,
        ))
        if state:
            self._restore_state(state)

    def on_redo(self):
        state = self.undo_manager.redo(UndoState(
            self.engine.items,
            self.engine.checked_paths,
            self.engine.use_absolute,
            self.engine.show_header,
        ))
        if state:
            self._restore_state(state)

    def _restore_state(self, state):
        self.engine.items = state.items
        self.engine.checked_paths = state.checked_paths
        self.engine.use_absolute = state.use_absolute
        self.engine.show_header = state.show_header

        self.radio_abs.setChecked(self.engine.use_absolute)
        self.radio_rel.setChecked(not self.engine.use_absolute)
        self.check_header.setChecked(self.engine.show_header)
        self._update_path_mode_ui()

        if self.engine.work_dir:
            self._uncheck_all_tree()
            for p_str in self.engine.checked_paths:
                self._set_tree_item_check(p_str, Qt.Checked)

        self._refresh_list()

    def _uncheck_all_tree(self):
        def walk(item):
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(0, Qt.Unchecked)
            for i in range(item.childCount()):
                walk(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def _show_toast(self, text, duration=None):
        if duration is None:
            duration = ToastNotification.DEFAULT_DURATION
        ToastNotification.show_toast(text, self, duration)

    def _on_tree_search_changed(self, text):
        keyword = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            self._filter_item(self.tree.topLevelItem(i), keyword)

    def _filter_item(self, item, keyword):
        match = not keyword or item.text(0).lower().contains(keyword)
        child_match = False
        for i in range(item.childCount()):
            if self._filter_item(item.child(i), keyword):
                child_match = True
        item.setHidden(not (match or child_match))
        return match or child_match

    def _open_shortcuts(self):
        from filecollector.gui.shortcuts_dialog import ShortcutsDialog
        ShortcutsDialog(self).exec()

    def _open_settings(self):
        QMessageBox.information(self, "语言设置",
                                "语言设置已保存，重启生效。\n\n"
                                "当前支持：跟随系统 / 中文 / English\n"
                                "（完整语言切换将在后续版本接入 i18n）")

    def _open_phrases_manager(self):
        from filecollector.gui.phrases_dialog import PhrasesDialog
        dlg = PhrasesDialog(self.common_phrases, self, select_mode=False)
        if dlg.exec() == QDialog.Accepted:
            self.common_phrases = dlg.phrases()
            if hasattr(self.engine, "save_common_phrases_to_disk"):
                self.engine.save_common_phrases_to_disk()

    def insert_text(self, above=True):
        current_row = self.list_widget.currentRow()
        if current_row == -1:
            index = len(self.engine.items) if above else len(self.engine.items)
        else:
            index = current_row if above else current_row + 1

        dialog = TextEditDialog(self, "插入自定义文字")
        if dialog.exec() != QDialog.Accepted:
            return
        text = dialog.get_text()
        if not text:
            return

        if self.common_phrases:
            from PySide6.QtWidgets import QPushButton, QHBoxLayout
            row = QHBoxLayout()
            use_btn = QPushButton("📋 使用常用语")
            skip_btn = QPushButton("直接插入")
            row.addWidget(use_btn)
            row.addWidget(skip_btn)
            dialog.layout().insertLayout(dialog.layout().count() - 1, row)
            use_btn.clicked.connect(lambda: self._open_phrase_picker(dialog))
            skip_btn.clicked.connect(dialog.accept)

        if dialog.exec() == QDialog.Accepted:
            text = dialog.get_text()
            if text:
                self._push_undo()
                self.engine.add_text(text, index=index)
                self._refresh_list()
                self.list_widget.setCurrentRow(index)
                self.status_bar.showMessage("已插入文字")
                self._show_toast("已插入文字")

    def _open_phrase_picker(self, text_dialog):
        from filecollector.gui.phrases_dialog import PhrasesDialog
        dlg = PhrasesDialog(self.common_phrases, self, select_mode=True)
        if dlg.exec() == QDialog.Accepted:
            phrase = dlg.phrase_selected
            text_dialog.set_text(phrase)


if __name__ == "__main__":
    pass