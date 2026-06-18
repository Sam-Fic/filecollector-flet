"""FileCollector 主窗口 (PySide6 移植版).

UX 设计目标: 与 GNOME 版本保持一致, 同时遵循 Qt 最佳实践.

关键 UX 移植要点 (对比 filecollector-gnome/src/window.blp / window.vala):
- 标题栏显示工作目录子标题 (匹配 update_subtitle).
- 三栏卡片式布局, 圆角 + 内边距 (匹配 style.css 里的 card / panel-frame).
- 列表中显示顺序编号、类型图标、状态标记 (匹配 queue_list factory.bind).
- 按钮状态随列表选中状态动态启用/禁用 (匹配 update_queue_buttons).
- 上方/下方插入文本仅在选中条目时启用 (匹配 insert_text 入口).
- 文件树懒加载展开 (匹配 load_directory_children_lazy).
- 目录勾选状态支持部分 / 全部 / 无 三态 (匹配 update_single_item_state).
- Toast 通知 (匹配 Adw.ToastOverlay).
- 搜索框仅在打开工作目录后可见 (匹配 search_entry.visible = true).
- 完整的撤销 / 重做支持 (匹配 UndoManager).
"""

from __future__ import annotations

import fnmatch
import os
import queue
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer, QSize, QSignalBlocker
from PySide6.QtGui import QAction, QFont, QDragEnterEvent, QDropEvent, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMenuBar, QMenu, QToolBar, QStatusBar,
    QSplitter, QTreeWidgetItem, QListWidget, QListWidgetItem,
    QTextEdit, QPushButton, QRadioButton, QCheckBox, QLabel, QVBoxLayout,
    QHBoxLayout, QFrame, QDialog, QLineEdit, QWidget, QFileDialog,
    QMessageBox, QButtonGroup, QSizePolicy,
)

from filecollector.models import ItemData
from filecollector.engine import FileCollectorEngine
from filecollector.utils import safe_read_file
from filecollector.i18n import (
    _, initialize as i18n_initialize,
    add_listener, remove_listener,
)
from filecollector.gui.dialogs import TextEditDialog
from filecollector.gui.file_tree import FileTreeWidget
from filecollector.gui.undo import UndoState, UndoManager
from filecollector.gui.style import get_stylesheet
from filecollector.gui.toast import ToastNotification
from filecollector.gui.ai_panel import AIPanel

import qtawesome as qta
from filecollector.gui.ai_settings_dialog import load_ai_settings, AISettingsDialog
from filecollector.cli import apply_cli_args


class FileCollectorApp(QMainWindow):
    status_message = Signal(str)

    BUTTON_HEIGHT = 32  # synced with config.BUTTON_HEIGHT

    def __init__(self):
        super().__init__()
        i18n_initialize()

        self.setWindowTitle(_("FileCollector - 文件收集与编排工具"))
        self.resize(1300, 780)
        self.setMinimumSize(960, 560)
        self.setStyleSheet(get_stylesheet())

        _icon_path = Path(__file__).resolve().parent.parent.parent.parent / "icons" / "filecollector.svg"
        if _icon_path.exists():
            self.setWindowIcon(QIcon(str(_icon_path)))

        self.engine = FileCollectorEngine()
        self.undo_manager = UndoManager()
        self.common_phrases: list[str] = []
        self._loading_state = False

        if hasattr(self.engine, "common_phrases") and self.engine.common_phrases:
            self.common_phrases = list(self.engine.common_phrases)
        if hasattr(self.engine, "load_common_phrases_from_disk"):
            self.engine.load_common_phrases_from_disk()
            self.common_phrases = list(self.engine.common_phrases)

        font = QFont()
        font.setPointSize(10)
        QApplication.setFont(font)

        self._setup_menu_bar()
        self._setup_toolbar()
        self._setup_central_widget()
        self._setup_status_bar()
        self._apply_button_height()
        self._connect_signals()
        self._update_button_states()

        self._refresh_tree()
        self._update_subtitle()
        self._refresh_list()

        # AI 边栏: 注入当前 settings + 工具执行器 + 状态快照回调
        self.ai_panel.configure(
            load_ai_settings(),
            tool_executor=self._execute_ai_tool,
            state_provider=self._ai_state_snapshot,
        )

        add_listener(self._on_language_changed)

        self.ipc_queue: queue.Queue = queue.Queue()
        self.ipc_stop = None
        self._start_ipc_server()

    def _on_language_changed(self, lang: str) -> None:
        """语言切换时重新翻译所有可见标签."""
        self.setWindowTitle(_("FileCollector - 文件收集与编排工具"))
        self._update_subtitle()
        self._retranslate_buttons_and_menus()
        self._refresh_list()

    def _retranslate_buttons_and_menus(self) -> None:
        """重新翻译按钮 / 菜单 / 复选框文本."""
        self.btn_undo.setText(_("撤销"))
        self.btn_redo.setText(_("重做"))
        self.open_folder_btn.setText(_("打开文件夹"))
        self.btn_add_external.setText(_("添加外部文件"))
        self.btn_add_text_above.setText(_("上方插入文本"))
        self.btn_add_text_below.setText(_("下方插入文本"))
        self.btn_move_up.setText(_("上移"))
        self.btn_move_down.setText(_("下移"))
        self.btn_delete.setText(_("删除"))
        self.btn_clear.setText(_("清空"))
        self.btn_generate.setText(_("生成合并文本"))
        self.btn_generate_clipboard.setText(_("生成合并文本到剪贴板"))
        self.radio_rel.setText(_("相对路径"))
        self.radio_abs.setText(_("使用绝对路径"))
        self.check_header.setText(_("在文件头部标注工作目录信息"))
        self.search_input.setPlaceholderText(_("搜索…"))
        self.act_open.setText(_("打开项目..."))
        self.act_save.setText(_("保存项目"))
        self.act_save_as.setText(_("项目另存为..."))
        self.act_exit.setText(_("退出(&X)"))
        self.act_settings.setText(_("语言设置"))
        self.act_phrases.setText(_("常用语管理(&M)"))
        self.act_shortcuts.setText(_("键盘快捷键"))
        self.act_about.setText(_("关于"))
        self.act_ai_settings.setText(_("AI 设置"))
        self.btn_ai_toggle.setText(_("AI"))
        self.menuBar().actions()[0].menu().setTitle(_("项目(&P)"))
        self.menuBar().actions()[1].menu().setTitle(_("设置(&S)"))
        self.menuBar().actions()[2].menu().setTitle(_("帮助(&H)"))

    # ==================================================================
    # IPC: single-instance communication
    # ==================================================================
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
        from filecollector.cli import apply_cli_args
        if apply_cli_args(self.engine, args, print_feedback=False):
            self.initialize_from_engine(self.engine)
            self.status_bar.showMessage(
                _("已从外部命令更新 (%d 项)") % len(self.engine.items)
            )
        else:
            self.status_bar.showMessage(_("外部命令解析失败"))

    def initialize_from_engine(self, engine: FileCollectorEngine) -> None:
        """从已有 engine 初始化 GUI 状态 (供 CLI --gui / IPC 使用)."""
        self._loading_state = True
        try:
            self.engine = engine
            self._update_subtitle()
            self._refresh_tree()
            for p_str in self.engine.checked_paths:
                self._set_tree_item_check(p_str, Qt.Checked)
            self.radio_abs.setChecked(self.engine.use_absolute)
            self.radio_rel.setChecked(not self.engine.use_absolute)
            self.check_header.setChecked(self.engine.show_header)
            self._update_path_mode_ui()
            self._refresh_list()
            self._update_button_states()
            self.status_bar.showMessage(
                _("已从 CLI 参数加载 %d 个项目") % len(self.engine.items)
            )
            self.search_input.setVisible(bool(self.engine.work_dir))
        finally:
            self._loading_state = False

    # ==================================================================
    # 菜单栏
    # ==================================================================
    def _setup_menu_bar(self):
        menu_bar = self.menuBar()

        project_menu = menu_bar.addMenu(_("项目(&P)"))
        self.act_open = QAction(_("打开项目..."), self)
        self.act_open.setIcon(qta.icon("fa5s.folder-open"))
        self.act_open.setShortcut("Ctrl+O")
        self.act_open.triggered.connect(self.load_project)
        project_menu.addAction(self.act_open)

        self.act_save = QAction(_("保存项目"), self)
        self.act_save.setIcon(qta.icon("fa5s.save"))
        self.act_save.setShortcut("Ctrl+S")
        self.act_save.triggered.connect(self.save_project)
        project_menu.addAction(self.act_save)

        self.act_save_as = QAction(_("项目另存为..."), self)
        self.act_save_as.setIcon(qta.icon("fa5s.copy"))
        self.act_save_as.setShortcut("Ctrl+Shift+S")
        self.act_save_as.triggered.connect(self.save_project_as)
        project_menu.addAction(self.act_save_as)
        project_menu.addSeparator()

        self.act_exit = QAction(_("退出(&X)"), self)
        self.act_exit.setIcon(qta.icon("fa5s.sign-out-alt"))
        self.act_exit.setShortcut("Ctrl+Q")
        self.act_exit.triggered.connect(self.close)
        project_menu.addAction(self.act_exit)

        settings_menu = menu_bar.addMenu(_("设置(&S)"))
        self.act_settings = QAction(_("语言设置"), self)
        self.act_settings.setIcon(qta.icon("fa5s.globe"))
        self.act_settings.setShortcut("Ctrl+,")
        self.act_settings.triggered.connect(self._open_settings)
        settings_menu.addAction(self.act_settings)

        self.act_phrases = QAction(_("常用语管理(&M)"), self)
        self.act_phrases.setIcon(qta.icon("fa5s.comment"))
        self.act_phrases.triggered.connect(self._open_phrases_manager)
        settings_menu.addAction(self.act_phrases)

        self.act_ai_settings = QAction(_("AI 设置"), self)
        self.act_ai_settings.setIcon(qta.icon("fa5s.cog"))
        self.act_ai_settings.triggered.connect(self._open_ai_settings)
        settings_menu.addAction(self.act_ai_settings)

        help_menu = menu_bar.addMenu(_("帮助(&H)"))
        self.act_shortcuts = QAction(_("键盘快捷键"), self)
        self.act_shortcuts.setIcon(qta.icon("fa5s.keyboard"))
        self.act_shortcuts.setShortcut("Ctrl+/")
        self.act_shortcuts.triggered.connect(self._open_shortcuts)
        help_menu.addAction(self.act_shortcuts)

        self.act_about = QAction(_("关于"), self)
        self.act_about.setIcon(qta.icon("fa5s.info-circle"))
        self.act_about.setShortcut("F1")
        self.act_about.triggered.connect(self._show_about)
        help_menu.addAction(self.act_about)

    # ==================================================================
    # 工具栏 (顶部操作区, 模仿 GNOME HeaderBar)
    # ==================================================================
    def _setup_toolbar(self):
        toolbar = QToolBar(_("主工具栏"))
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setContentsMargins(0, 0, 0, 0)
        self.addToolBar(toolbar)

        self.btn_undo = QPushButton(_("撤销"))
        self.btn_undo.setIcon(qta.icon("fa5s.undo"))
        self.btn_undo.setToolTip("Ctrl+Z")
        self.btn_undo.setObjectName("FlatButton")
        self.btn_undo.setEnabled(False)
        self.btn_undo.clicked.connect(self.on_undo)
        toolbar.addWidget(self.btn_undo)

        self.btn_redo = QPushButton(_("重做"))
        self.btn_redo.setIcon(qta.icon("fa5s.redo"))
        self.btn_redo.setToolTip("Ctrl+Shift+Z")
        self.btn_redo.setObjectName("FlatButton")
        self.btn_redo.setEnabled(False)
        self.btn_redo.clicked.connect(self.on_redo)
        toolbar.addWidget(self.btn_redo)

        toolbar.addSeparator()

        self.open_folder_btn = QPushButton(_("打开文件夹"))
        self.open_folder_btn.setIcon(qta.icon("fa5s.folder-open"))
        self.open_folder_btn.setToolTip(_("选择工作目录，左侧加载目录树"))
        self.open_folder_btn.clicked.connect(self.open_folder)
        toolbar.addWidget(self.open_folder_btn)

        toolbar.addSeparator()

        self.work_dir_label = QLabel(_("当前工作目录: 未设置"))
        self.work_dir_label.setObjectName("WorkDirLabel")
        self.work_dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        toolbar.addWidget(self.work_dir_label)

        # 弹性占位, 将 AI 按钮推到最右
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        spacer.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        toolbar.addWidget(spacer)

        self.btn_ai_toggle = QPushButton(_("AI"))
        self.btn_ai_toggle.setIcon(qta.icon("fa5s.robot"))
        self.btn_ai_toggle.setCheckable(True)
        self.btn_ai_toggle.setObjectName("FlatButton")
        self.btn_ai_toggle.setToolTip(_("展开 / 收起 AI 助手边栏"))
        self.btn_ai_toggle.toggled.connect(self._on_ai_toggle)
        toolbar.addWidget(self.btn_ai_toggle)

    # ==================================================================
    # 中央区域 (三栏分割器, 卡片式)
    # ==================================================================
    def _setup_central_widget(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)

        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        # 顶部 0px (紧贴工具栏), 底部 0px (紧贴状态栏), 左右 8px
        wrapper_layout.setContentsMargins(8, 0, 8, 0)
        wrapper_layout.addWidget(splitter)
        self.setCentralWidget(wrapper)

        # --- 左栏: 文件树 ---
        tree_panel = QFrame()
        tree_panel.setObjectName("LeftPanel")
        tree_layout = QVBoxLayout(tree_panel)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.setSpacing(0)

        title = QLabel(_("资源管理器"))
        title.setObjectName("PanelTitle")
        tree_layout.addWidget(title)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("TreeSearch")
        self.search_input.setPlaceholderText(_("搜索…"))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_tree_search_changed)
        self.search_input.setVisible(False)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(12, 0, 12, 6)
        search_row.addWidget(self.search_input)
        search_row.addSpacing(0)
        tree_layout.addLayout(search_row)

        self.tree = FileTreeWidget()
        self.tree.setMinimumWidth(200)
        self.tree.setObjectName("FileTree")
        self.tree.checked_files_changed.connect(self._on_tree_check_changed)
        tree_layout.addWidget(self.tree)

        splitter.addWidget(tree_panel)

        # --- 中栏: 编排列表 ---
        middle_panel = QFrame()
        middle_panel.setObjectName("MiddlePanel")
        middle_layout = QVBoxLayout(middle_panel)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(0)

        middle_title = QLabel(_("输出编排列表"))
        middle_title.setObjectName("PanelTitle")
        middle_layout.addWidget(middle_title)

        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.MoveAction)
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.list_widget.setMinimumWidth(400)
        self.list_widget.setUniformItemSizes(False)
        middle_layout.addWidget(self.list_widget)

        btn_row1 = QHBoxLayout()
        btn_row1.setContentsMargins(12, 8, 12, 4)
        btn_row1.setSpacing(6)
        self.btn_add_external = QPushButton(_("添加外部文件"))
        self.btn_add_external.setIcon(qta.icon("fa5s.file-import"))
        self.btn_add_external.setShortcut("Ctrl+E")
        self.btn_add_external.setToolTip("Ctrl+E")
        self.btn_add_text_above = QPushButton(_("上方插入文本"))
        self.btn_add_text_above.setIcon(qta.icon("fa5s.arrow-up"))
        self.btn_add_text_above.setShortcut("Ctrl+I")
        self.btn_add_text_above.setToolTip("Ctrl+I")
        self.btn_add_text_below = QPushButton(_("下方插入文本"))
        self.btn_add_text_below.setIcon(qta.icon("fa5s.arrow-down"))
        self.btn_add_text_below.setShortcut("Ctrl+Shift+I")
        self.btn_add_text_below.setToolTip("Ctrl+Shift+I")
        btn_row1.addWidget(self.btn_add_external)
        btn_row1.addWidget(self.btn_add_text_above)
        btn_row1.addWidget(self.btn_add_text_below)
        middle_layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        btn_row2.setContentsMargins(12, 0, 12, 4)
        btn_row2.setSpacing(6)
        self.btn_move_up = QPushButton(_("上移"))
        self.btn_move_up.setIcon(qta.icon("fa5s.chevron-up"))
        self.btn_move_up.setShortcut("Ctrl+Up")
        self.btn_move_up.setToolTip("Ctrl+Up")
        self.btn_move_down = QPushButton(_("下移"))
        self.btn_move_down.setIcon(qta.icon("fa5s.chevron-down"))
        self.btn_move_down.setShortcut("Ctrl+Down")
        self.btn_move_down.setToolTip("Ctrl+Down")
        self.btn_delete = QPushButton(_("删除"))
        self.btn_delete.setIcon(qta.icon("fa5s.trash"))
        self.btn_delete.setShortcut("Delete")
        self.btn_delete.setToolTip("Delete")
        self.btn_clear = QPushButton(_("清空"))
        self.btn_clear.setIcon(qta.icon("fa5s.ban", color="white"))
        self.btn_clear.setShortcut("Ctrl+N")
        self.btn_clear.setToolTip("Ctrl+N")
        self.btn_clear.setObjectName("DestructiveAction")
        btn_row2.addWidget(self.btn_move_up)
        btn_row2.addWidget(self.btn_move_down)
        btn_row2.addWidget(self.btn_delete)
        btn_row2.addStretch()
        btn_row2.addWidget(self.btn_clear)
        middle_layout.addLayout(btn_row2)

        opt_frame = QFrame()
        opt_layout = QHBoxLayout(opt_frame)
        opt_layout.setContentsMargins(12, 4, 12, 4)
        opt_layout.setSpacing(14)

        self.radio_rel = QRadioButton(_("相对路径"))
        self.radio_abs = QRadioButton(_("使用绝对路径"))
        self.path_mode_group = QButtonGroup()
        self.path_mode_group.addButton(self.radio_rel)
        self.path_mode_group.addButton(self.radio_abs)
        self.radio_rel.setChecked(True)
        opt_layout.addWidget(self.radio_rel)
        opt_layout.addWidget(self.radio_abs)
        self.check_header = QCheckBox(_("在文件头部标注工作目录信息"))
        opt_layout.addWidget(self.check_header)
        opt_layout.addStretch()
        middle_layout.addWidget(opt_frame)

        btn_row3 = QHBoxLayout()
        btn_row3.setContentsMargins(12, 4, 12, 12)
        btn_row3.setSpacing(6)
        self.btn_generate = QPushButton(_("生成合并文本"))
        self.btn_generate.setIcon(qta.icon("fa5s.file-export", color="white"))
        self.btn_generate.setObjectName("SuggestedAction")
        self.btn_generate.setShortcut("Ctrl+G")
        self.btn_generate.setToolTip("Ctrl+G")
        self.btn_generate_clipboard = QPushButton(_("生成合并文本到剪贴板"))
        self.btn_generate_clipboard.setIcon(qta.icon("fa5s.clipboard", color="white"))
        self.btn_generate_clipboard.setObjectName("SuggestedAction")
        self.btn_generate_clipboard.setShortcut("Ctrl+Shift+C")
        self.btn_generate_clipboard.setToolTip("Ctrl+Shift+C")
        btn_row3.addWidget(self.btn_generate)
        btn_row3.addWidget(self.btn_generate_clipboard)
        middle_layout.addLayout(btn_row3)

        splitter.addWidget(middle_panel)

        # --- 右栏: 预览 ---
        preview_panel = QFrame()
        preview_panel.setObjectName("RightPanel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)

        preview_title = QLabel(_("预览"))
        preview_title.setObjectName("PanelTitle")
        preview_layout.addWidget(preview_title)

        self.preview = QTextEdit()
        self.preview.setObjectName("PreviewView")
        self.preview.setReadOnly(True)
        self.preview.setMinimumWidth(200)
        preview_layout.addWidget(self.preview)

        splitter.addWidget(preview_panel)

        # --- 右栏: AI 助手 (默认隐藏, 通过工具栏按钮展开) ---
        self.ai_panel = AIPanel()
        self.ai_panel.setMinimumWidth(300)
        self.ai_panel.setVisible(False)
        splitter.addWidget(self.ai_panel)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setStretchFactor(3, 3)
        splitter.setSizes([280, 520, 380, 360])
        self._splitter = splitter

    # ==================================================================
    # 状态栏
    # ==================================================================
    def _setup_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(_("就绪"))

    def _apply_button_height(self):
        """统一所有按钮高度, 避免不同 padding 导致视觉高度不一."""
        for btn in self.findChildren(QPushButton):
            btn.setFixedHeight(self.BUTTON_HEIGHT)

    # ==================================================================
    # 信号连接
    # ==================================================================
    def _connect_signals(self):
        self.btn_add_external.clicked.connect(self.add_external_files)
        self.btn_add_text_above.clicked.connect(
            lambda: self.insert_text(above=True))
        self.btn_add_text_below.clicked.connect(
            lambda: self.insert_text(above=False))
        self.btn_move_up.clicked.connect(self.move_up)
        self.btn_move_down.clicked.connect(self.move_down)
        self.btn_delete.clicked.connect(self.delete_item)
        self.btn_clear.clicked.connect(self.clear_items)
        self.btn_generate.clicked.connect(self.generate_txt)
        self.btn_generate_clipboard.clicked.connect(self.generate_to_clipboard)

        self.path_mode_group.buttonClicked.connect(self._on_path_mode_changed)
        self.check_header.stateChanged.connect(self._on_header_check_changed)

        self.list_widget.currentItemChanged.connect(
            self._on_list_selection_changed)
        self.list_widget.itemDoubleClicked.connect(
            self._on_list_item_double_clicked)

        self.list_widget.setAcceptDrops(True)
        self.list_widget.installEventFilter(self)
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)

    # ==================================================================
    # 子标题更新 (匹配 GNOME update_subtitle)
    # ==================================================================
    def _update_subtitle(self) -> None:
        if self.engine.work_dir:
            self.work_dir_label.setText(
                _("当前工作目录: %s") % str(self.engine.work_dir)
            )
        else:
            self.work_dir_label.setText(_("当前工作目录: 未设置"))

    # ==================================================================
    # 按钮状态管理 (匹配 GNOME update_queue_buttons)
    # ==================================================================
    def _update_button_states(self) -> None:
        sel = self.list_widget.currentRow()
        has_sel = sel >= 0 and sel < len(self.engine.items)
        many = len(self.engine.items) > 1

        self.btn_add_text_above.setEnabled(has_sel)
        self.btn_add_text_below.setEnabled(has_sel)
        self.btn_move_up.setEnabled(has_sel and many and sel > 0)
        self.btn_move_down.setEnabled(
            has_sel and many and sel < len(self.engine.items) - 1)
        self.btn_delete.setEnabled(has_sel)

        self.btn_undo.setEnabled(self.undo_manager.can_undo)
        self.btn_redo.setEnabled(self.undo_manager.can_redo)

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
                added = 0
                for url in urls:
                    file_path = url.toLocalFile()
                    if os.path.isfile(file_path):
                        self.engine.add_file(file_path, force_absolute=True)
                        added += 1
                if added:
                    self._push_undo()
                    self._refresh_list()
                    self.status_bar.showMessage(_("已添加 %d 个外部文件") % added)
                return True
        return super().eventFilter(obj, event)

    # ==================================================================
    # 树状目录 (由 FileTreeWidget 承担, 主窗口仅做引擎同步)
    # ==================================================================
    def _refresh_tree(self) -> None:
        self.tree.set_work_dir(self.engine.work_dir)
        if self.engine.checked_paths:
            self.tree.set_checked_paths(set(self.engine.checked_paths))
        self.search_input.setVisible(bool(self.engine.work_dir))

    def _on_tree_check_changed(self) -> None:
        """FileTreeWidget 内部状态变化 → 同步到 engine.items."""
        self._push_undo()
        self.engine.checked_paths = self.tree.get_checked_paths()
        self._sync_items_from_tree()
        self._refresh_list()
        self.status_bar.showMessage(
            _("已勾选 %d 个文件") % len(self.engine.checked_paths)
        )

    def _sync_items_from_tree(self) -> None:
        """根据 tree 勾选状态, 重建 engine.items 中与目录树对应的部分.

        策略: 保留已存在的'文件绝对路径型'条目以及所有'文字型'条目, 删除
        已取消勾选的'相对路径型'条目, 追加新增勾选的文件.
        """
        from filecollector.models import ItemData as _ID
        checked_now = set(self.engine.checked_paths)
        checked_prev: set[str] = set()
        for it in self.engine.items:
            if it.type == "file" and not it.force_absolute:
                checked_prev.add(it.path)

        for path in checked_now - checked_prev:
            self.engine.items.append(
                _ID(type_="file", path=path, force_absolute=False)
            )
        for path in checked_prev - checked_now:
            self.engine.items = [
                it for it in self.engine.items
                if not (it.type == "file" and it.path == path and not it.force_absolute)
            ]

    def _restore_tree_checks(self, checked_paths) -> None:
        self.tree.set_checked_paths(set(checked_paths))

    def _on_tree_search_changed(self, text: str) -> None:
        self.tree.filter_items(text)

    # ==================================================================
    # 编排列表
    # ==================================================================
    def _refresh_list(self):
        self._loading_state = True
        try:
            self.list_widget.clear()
            for idx, data in enumerate(self.engine.items):
                display = self._get_display_text(idx, data)
                lw_item = QListWidgetItem(display)
                lw_item.setData(Qt.UserRole, data)
                self.list_widget.addItem(lw_item)
        finally:
            self._loading_state = False
        self._update_button_states()

    def _get_display_text(self, idx: int, data: ItemData) -> str:
        if data.type == "file":
            p = Path(data.path)
            if data.force_absolute:
                return f"{idx+1}. {p.name}  {_('(绝对路径)')}"
            else:
                return f"{idx+1}. {p.name}"
        else:
            preview = data.content
            if len(preview) > 30:
                preview = preview[:30] + "..."
            return f"{idx+1}. {preview}"

    def add_external_files(self):
        self._push_undo()
        files, _selected = QFileDialog.getOpenFileNames(self, _("选择外部文件"))
        if files:
            for f in files:
                abs_path = str(Path(f).resolve())
                self.engine.add_file(abs_path, force_absolute=True)
            self._refresh_list()
            self.status_bar.showMessage(_("已添加 %d 个外部文件") % len(files))
        else:
            self.undo_manager.undo_stack.pop()

    def move_up(self):
        row = self.list_widget.currentRow()
        if row > 0:
            self._push_undo()
            self.engine.move_item(row, row - 1)
            self._refresh_list()
            self.list_widget.setCurrentRow(row - 1)

    def move_down(self):
        row = self.list_widget.currentRow()
        if row < len(self.engine.items) - 1:
            self._push_undo()
            self.engine.move_item(row, row + 1)
            self._refresh_list()
            self.list_widget.setCurrentRow(row + 1)

    def delete_item(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        self._push_undo()
        data = self.engine.items[row]
        if data.type == "file" and not data.force_absolute:
            if data.path in self.engine.checked_paths:
                self.engine.checked_paths.discard(data.path)
                self._set_tree_item_check(data.path, Qt.Unchecked)
        self.engine.remove_item(row)
        self._refresh_list()
        self.status_bar.showMessage(_("条目已删除"))

    def clear_items(self):
        reply = QMessageBox.question(
            self, _("确认"), _("确定清空编排列表吗？"),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._push_undo()
        for path in list(self.engine.checked_paths):
            self._set_tree_item_check(path, Qt.Unchecked)
        self.tree.refresh_all_ancestor_states()
        self.engine.clear()
        self._refresh_list()
        self.status_bar.showMessage(_("编排列表已清空"))

    def _set_tree_item_check(self, abs_path: str, state: Qt.CheckState) -> None:
        def search(item):
            if item.data(0, ROLE_IS_DIR) or item.data(0, ROLE_IS_PLACEHOLDER):
                return False
            if item.data(0, ROLE_PATH) == abs_path:
                if item.checkState(0) != state:
                    self.tree._loading = True
                    try:
                        item.setCheckState(0, state)
                    finally:
                        self.tree._loading = False
                self.tree._update_ancestor_states(item)
                return True
            for i in range(item.childCount()):
                if search(item.child(i)):
                    return True
            return False

        from filecollector.gui.file_tree import ROLE_PATH, ROLE_IS_DIR, ROLE_IS_PLACEHOLDER
        for i in range(self.tree.topLevelItemCount()):
            search(self.tree.topLevelItem(i))

    # ==================================================================
    # 列表交互
    # ==================================================================
    def _on_list_selection_changed(self, current, previous):
        self._update_button_states()
        if current is None:
            self.preview.clear()
            return
        data = current.data(Qt.UserRole)
        if not isinstance(data, ItemData):
            return
        self._show_preview(data)

    def _on_list_item_double_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if isinstance(data, ItemData) and data.type == "text":
            dialog = TextEditDialog(
                self, _("编辑文字"), initial_text=data.content,
                show_phrases_button=False,
            )
            if dialog.exec() == QDialog.Accepted:
                new_text = dialog.get_text()
                if new_text:
                    data.content = new_text
                    self._refresh_list()
                    self.list_widget.setCurrentRow(
                        self.list_widget.currentRow())
                    self._show_preview(data)
                    self.status_bar.showMessage(_("文字已更新"))

    def _sync_items_from_list(self):
        new_items = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            data = item.data(Qt.UserRole)
            if isinstance(data, ItemData):
                new_items.append(data)
        self.engine.items = new_items

    def _on_rows_moved(self, parent, start, end, destination, row):
        if self._loading_state:
            return
        self._push_undo()
        self._sync_items_from_list()
        self._refresh_list()

    # ==================================================================
    # 预览区
    # ==================================================================
    def _show_preview(self, data: ItemData):
        self.preview.clear()
        if data.type == "file":
            if not os.path.exists(data.path):
                self.preview.setPlainText(_("[文件不存在]"))
                return
            try:
                content, enc = safe_read_file(data.path, max_preview_lines=50)
                preview_text = _("--- 文件预览 (编码: %s) ---" +
                                 chr(10) + " %s") % (enc, content)
                self.preview.setPlainText(preview_text)
            except Exception as e:
                self.preview.setPlainText(_("读取错误: %s") % e)
        else:
            self.preview.setPlainText(data.content)

    # ==================================================================
    # 路径模式
    # ==================================================================
    def _update_path_mode_ui(self):
        self.check_header.setEnabled(not self.engine.use_absolute)

    def _on_header_check_changed(self, state: int):
        if self._loading_state:
            return
        # PySide6 中 Qt.Checked 是枚举, 直接与 int 比较会得到 False,
        # 必须用 int() 转一次. 该 bug 之前让 GUI 勾选无法写入 engine.
        self.engine.show_header = int(state) == int(Qt.Checked.value)

    def _on_path_mode_changed(self, button):
        if self._loading_state:
            return
        self._push_undo()
        self.engine.use_absolute = self.radio_abs.isChecked()
        self._update_path_mode_ui()
        self._refresh_list()

    # ==================================================================
    # 生成 TXT
    # ==================================================================
    def generate_txt(self):
        if not self.engine.items:
            QMessageBox.warning(self, _("警告"), _("编排列表为空，无法生成。"))
            return
        file_path, _selected = QFileDialog.getSaveFileName(
            self, _("保存合并文本"), "",
            _("Text files (*.txt);;All files (*)"),
        )
        if not file_path:
            return
        if not file_path.lower().endswith('.txt'):
            file_path += '.txt'
        try:
            self.engine.export(file_path)
            self.status_bar.showMessage(_("TXT 已生成: %s") % file_path)
            ToastNotification.show_toast(
                _("文件已保存到:" + chr(10) + "%s") % file_path, self,
                ToastNotification.DEFAULT_DURATION + 1000,
            )
            self._open_file_location(file_path)
        except Exception as e:
            QMessageBox.critical(self, _("错误"), _(
                "生成 TXT 失败:" + chr(10) + "%s") % e)

    def generate_to_clipboard(self):
        if not self.engine.items:
            QMessageBox.warning(self, _("警告"), _("编排列表为空，无法生成。"))
            return
        try:
            from filecollector.config import get_clipboard_staging_path
            file_path = get_clipboard_staging_path()
            self.engine.export(file_path)
            import subprocess
            if sys.platform == "win32":
                subprocess.run(
                    ["clip"],
                    input=open(file_path, "rb").read(),
                    check=False,
                )
            elif sys.platform == "darwin":
                subprocess.run(
                    ["pbcopy"],
                    input=open(file_path, "rb").read(),
                    check=False,
                )
            else:
                subprocess.run(
                    ["xclip", "-selection", "clipboard", file_path],
                    check=False,
                )
            self.status_bar.showMessage(_("合并文本已复制到剪贴板"))
            self._show_toast(_("合并文本已复制到剪贴板"))
        except Exception as e:
            QMessageBox.critical(self, _("错误"), _(
                "复制到剪贴板失败:" + chr(10) + "%s") % e)

    def _open_file_location(self, path: str):
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
        directory = QFileDialog.getExistingDirectory(self, _("选择工作文件夹"))
        if not directory:
            return
        self._push_undo()
        self.engine.work_dir = Path(directory).resolve()
        self._update_subtitle()
        self._refresh_tree()
        self._refresh_list()
        self.status_bar.showMessage(
            _("已设置工作目录: %s") % self.engine.work_dir
        )

    # ==================================================================
    # 项目保存/加载
    # ==================================================================
    def save_project(self):
        if not getattr(self.engine, "project_file", None):
            return self.save_project_as()
        self._write_project(self.engine.project_file)

    def save_project_as(self):
        file_path, _selected = QFileDialog.getSaveFileName(
            self, _("保存项目"), "",
            _("Project (*.project.json *.fcol *.fcol.json);;Project JSON (*.project.json);;GNOME Project (*.fcol *.fcol.json)"),
            selectedFilter="Project (*.project.json *.fcol *.fcol.json)",
        )
        if file_path:
            if not (file_path.endswith(".project.json")
                    or file_path.endswith(".fcol")
                    or file_path.endswith(".fcol.json")):
                file_path += ".project.json"
            self._write_project(file_path)

    def _write_project(self, file_path: str):
        try:
            self.engine.common_phrases = list(self.common_phrases)
            self.engine.save_project(file_path)
            self.engine.project_file = file_path
            self.status_bar.showMessage(_("项目已保存: %s") % file_path)
            self._show_toast(_("项目已保存: %s") % Path(file_path).name)
        except Exception as e:
            QMessageBox.critical(self, _("保存失败"), str(e))

    def load_project(self):
        file_path, _selected = QFileDialog.getOpenFileName(
            self, _("打开项目"), "",
            _("Project (*.project.json *.fcol *.fcol.json);;Project JSON (*.project.json);;GNOME Project (*.fcol *.fcol.json)"),
            selectedFilter="Project (*.project.json *.fcol *.fcol.json)",
        )
        if not file_path:
            return
        try:
            self.engine.load_project(file_path)
            self.initialize_from_engine(self.engine)
            self.engine.project_file = file_path
            self.common_phrases = list(self.engine.common_phrases)
            self.status_bar.showMessage(_("项目已加载: %s") % file_path)
            self._show_toast(_("项目已加载: %s") % Path(file_path).name)
        except Exception as e:
            QMessageBox.critical(
                self, _("加载失败"),
                _("项目文件损坏或格式不正确:" + chr(10) + "%s") % e,
            )
            traceback.print_exc()

    # ==================================================================
    # 关于 / 帮助
    # ==================================================================
    def _show_about(self):
        QMessageBox.about(
            self, _("关于 FileCollector"),
            "<h3>FileCollector</h3>"
            "<p>" + _("文件收集与编排工具") + "</p>"
            "<p>" + _("跨平台支持 Windows / macOS / Linux。") + "</p>"
            "<p><b>" + _("主要功能：") + "</b></p>"
            "<ul>"
            "<li>" + _("目录树浏览 + 多选勾选") + "</li>"
            "<li>" + _("拖放排序 + 撤销 / 重做") + "</li>"
            "<li>" + _("文字插入 + 常用语管理") + "</li>"
            "<li>" + _("智能编码检测 (UTF-8 / GBK / 拉丁系)") + "</li>"
            "<li>" + _("项目保存 / 加载 (.project.json / .fcol)") + "</li>"
            "<li>" + _("中英文切换 (跟随系统 / 中文 / English)") + "</li>"
            "<li>" + _("完整键盘快捷键支持") + "</li>"
            "</ul>"
            "<p style='color:#5e5c64;'>"
            + _("开发者：Sam-Fic | License: MIT") +
            "</p>"
            "<p><a href='https://github.com/Sam-Fic/filecollector'>"
            + _("访问 GitHub 仓库") +
            "</a></p>"
        )

    def _open_shortcuts(self):
        from filecollector.gui.shortcuts_dialog import ShortcutsDialog
        ShortcutsDialog(self).exec()

    def _open_settings(self):
        from filecollector.gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()

    def _open_phrases_manager(self):
        from filecollector.gui.phrases_dialog import PhrasesDialog
        dlg = PhrasesDialog(self.common_phrases, self, select_mode=False)
        if dlg.exec() == QDialog.Accepted:
            self.common_phrases = dlg.phrases()
            if hasattr(self.engine, "save_common_phrases_to_disk"):
                self.engine.common_phrases = self.common_phrases
                self.engine.save_common_phrases_to_disk()

    # ==================================================================
    # AI 助手
    # ==================================================================
    def _open_ai_settings(self):
        dlg = AISettingsDialog(self)
        if dlg.exec() == QDialog.Accepted:
            # 用户改完设置后, 重新配置 AI 面板
            self.ai_panel.configure(
                load_ai_settings(),
                tool_executor=self._execute_ai_tool,
                state_provider=self._ai_state_snapshot,
            )
            self.status_bar.showMessage(_("AI 设置已更新"))

    def _on_ai_toggle(self, checked: bool) -> None:
        self.ai_panel.setVisible(checked)
        if checked:
            sizes = self._splitter.sizes()
            # 若 AI 面板拿到的宽度为 0, 给一个合理默认
            if len(sizes) >= 4 and sizes[3] < 100:
                sizes[3] = 360
                self._splitter.setSizes(sizes)

    def _ai_state_snapshot(self) -> tuple:
        """供 system prompt 使用: 返回 (work_dir, items 列表, use_absolute, show_header)."""
        items = []
        for it in self.engine.items:
            if it.type == "file":
                items.append({
                    "type": "file",
                    "path": it.path,
                    "force_absolute": bool(it.force_absolute),
                })
            else:
                items.append({
                    "type": "text",
                    "content": it.content or "",
                })
        work_dir = str(self.engine.work_dir) if self.engine.work_dir else None
        return work_dir, items, bool(self.engine.use_absolute), bool(self.engine.show_header)

    def _execute_ai_tool(self, name: str, arguments: dict) -> str:
        """AI 边栏工具调用入口: 把 LLM 决策映射到 ``apply_cli_args`` / engine 直接修改,
        统一走和 CLI / IPC / MCP 相同的 mutation 语义."""
        try:
            return self._dispatch_ai_tool(name, arguments or {})
        except Exception as e:  # noqa: BLE001
            return _("执行出错: %s") % e

    def _dispatch_ai_tool(self, name: str, args: dict) -> str:
        if name == "set_work_dir":
            path = (args.get("path") or "").strip()
            if not path:
                return _("错误: path 不能为空")
            self._push_undo()
            ok = apply_cli_args(
                self.engine, ["--work-dir", path], print_feedback=False)
            if not ok:
                return _("错误: 切换工作目录失败")
            # 工作目录变化需要重建 tree, 清空 checked paths
            self.engine.checked_paths.clear()
            self._update_subtitle()
            self._refresh_tree()
            self._refresh_list()
            self._update_button_states()
            return _("工作目录已切换到 %s") % self.engine.work_dir

        if name == "add_files":
            paths = args.get("paths") or []
            if not isinstance(paths, list) or not paths:
                return _("错误: paths 必须是非空数组")
            self._push_undo()
            added, skipped = [], []
            added_external: list[str] = []
            work_dir = self.engine.work_dir

            for p in paths:
                if not isinstance(p, str) or not p.strip():
                    skipped.append(str(p))
                    continue
                if not os.path.isfile(p):
                    skipped.append(p)
                    continue
                abs_path = str(Path(p).resolve())

                # 决定路径模式:
                #   - 在 work_dir 内 → 相对路径 (force_absolute=False),
                #     同步到 tree 的勾选状态, 用户在文件树里也能看到勾;
                #   - 在 work_dir 外 → 绝对路径 (force_absolute=True),
                #     这类文件不会出现在文件树里.
                inside_work_dir = False
                if work_dir is not None:
                    try:
                        inside_work_dir = Path(
                            abs_path).is_relative_to(work_dir)
                    except (ValueError, AttributeError):
                        inside_work_dir = False

                if inside_work_dir:
                    # 树是懒加载的, 即便文件在 work_dir 内, 如果它所在
                    # 的子目录尚未展开, 它就不在 _all_items 中. 先按需
                    # 自顶向下展开父目录链, 然后再走 --select-file 路径.
                    if self.tree._all_items.get(abs_path) is None:
                        self.tree._eager_load_for_path(abs_path)
                    apply_cli_args(
                        self.engine, ["--select-file", abs_path],
                        print_feedback=False)
                    added.append(abs_path)
                else:
                    from filecollector.models import ItemData as _ID
                    self.engine.items.append(
                        _ID(type_="file", path=abs_path, force_absolute=True)
                    )
                    added_external.append(abs_path)

            # 批量勾选 tree 项. 用 QSignalBlocker 抑制循环期间的
            # checked_files_changed — 否则 _on_tree_check_changed 会
            # 用 tree.get_checked_paths() 覆盖 engine.checked_paths,
            # 把尚未勾选的文件从 items 中误删.
            with QSignalBlocker(self.tree):
                for p in added:
                    self._set_tree_item_check(p, Qt.Checked)
            # 解开 blocker 后, 主动 emit 一次, 让 main_window 把当前
            # tree 状态正确同步到 engine.items
            self.tree.checked_files_changed.emit()
            self.tree.refresh_all_ancestor_states()
            self._refresh_list()
            total_added = len(added) + len(added_external)
            if total_added and not skipped:
                return _("已添加 %d 个文件") % total_added
            if total_added and skipped:
                return _("已添加 %d 个文件 (跳过 %d 个无效路径)") % (
                    total_added, len(skipped))
            return _("已跳过所有 %d 个路径 (文件不存在)") % len(skipped)

        if name == "add_text":
            text = args.get("text") or ""
            position = args.get("position")
            if not isinstance(text, str):
                return _("错误: text 必须是字符串")
            self._push_undo()
            ok = apply_cli_args(
                self.engine, ["--add-text", text], print_feedback=False)
            if not ok:
                return _("错误: 插入文字失败")
            new_index = len(self.engine.items) - 1
            if position is not None:
                try:
                    target = int(position)
                except (TypeError, ValueError):
                    target = new_index
                target = max(0, min(target, len(self.engine.items) - 1))
                if target != new_index:
                    apply_cli_args(
                        self.engine,
                        ["--move", str(new_index), str(target)],
                        print_feedback=False,
                    )
                    new_index = target
            self._refresh_list()
            self.list_widget.setCurrentRow(new_index)
            return _("已插入文字")

        if name == "remove_item":
            try:
                idx = int(args.get("index"))
            except (TypeError, ValueError):
                return _("错误: index 必须是整数")
            if not (0 <= idx < len(self.engine.items)):
                return _("错误: index %d 超出范围 (0..%d)") % (idx, len(self.engine.items) - 1)
            self._push_undo()
            data = self.engine.items[idx]
            if data.type == "file" and not data.force_absolute:
                if data.path in self.engine.checked_paths:
                    self.engine.checked_paths.discard(data.path)
                    self._set_tree_item_check(data.path, Qt.Unchecked)
            apply_cli_args(
                self.engine, ["--remove", str(idx)], print_feedback=False)
            self._refresh_list()
            return _("已删除索引 %d") % idx

        if name == "move_item":
            try:
                f = int(args.get("from_index"))
                t = int(args.get("to_index"))
            except (TypeError, ValueError):
                return _("错误: from_index / to_index 必须是整数")
            n = len(self.engine.items)
            if not (0 <= f < n and 0 <= t < n):
                return _("错误: 索引超出范围 (0..%d)") % (n - 1)
            if f == t:
                return _("源与目标相同, 无需移动")
            self._push_undo()
            apply_cli_args(
                self.engine, ["--move", str(f), str(t)], print_feedback=False)
            self._refresh_list()
            self.list_widget.setCurrentRow(t)
            return _("已将 [%d] 移动到 [%d]") % (f, t)

        if name == "clear_items":
            self._push_undo()
            for p in list(self.engine.checked_paths):
                self._set_tree_item_check(p, Qt.Unchecked)
            self.tree.refresh_all_ancestor_states()
            apply_cli_args(self.engine, ["--clear"], print_feedback=False)
            self._refresh_list()
            return _("已清空编排列表")

        if name == "set_use_absolute":
            value = bool(args.get("value"))
            self._push_undo()
            self.engine.use_absolute = value
            self.radio_abs.setChecked(value)
            self.radio_rel.setChecked(not value)
            self._update_path_mode_ui()
            return _("路径模式: %s") % (_("绝对路径") if value else _("相对路径"))

        if name == "set_show_header":
            value = bool(args.get("value"))
            self.engine.show_header = value
            self.check_header.setChecked(value)
            return _("头部信息: %s") % (_("已开启") if value else _("已关闭"))

        if name == "list_files":
            return self._ai_list_files(args)

        if name == "read_file":
            return self._ai_read_file(args)

        if name == "list_items":
            return self._ai_list_items(args)

        return _("未知工具: %s") % name

    # ==================================================================
    # AI 工具: list_files - 扫描目录供 agent 探索
    # ==================================================================
    # 跳过常见的构建 / VCS / 缓存目录, 避免把无关文件塞给 LLM.
    _AI_SKIP_DIRS = {
        ".git", ".hg", ".svn", ".idea", ".vscode", ".venv", "venv", "env",
        "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache",
        "dist", "build", ".next", ".nuxt", "target", ".gradle",
    }

    def _ai_list_files(self, args: dict) -> str:
        pattern = (args.get("pattern") or "").strip() or None
        directory = (args.get("directory") or "").strip() or None
        try:
            max_depth = int(args.get("max_depth") or 8)
        except (TypeError, ValueError):
            max_depth = 8
        try:
            max_results = int(args.get("max_results") or 200)
        except (TypeError, ValueError):
            max_results = 200
        max_depth = max(1, min(max_depth, 20))
        max_results = max(1, min(max_results, 2000))

        if directory:
            root = Path(directory).expanduser()
        else:
            root = self.engine.work_dir
        if root is None:
            return _("错误: 尚未设置工作目录, 也未提供 directory 参数")
        if not root.exists() or not root.is_dir():
            return _("错误: 目录不存在: %s") % str(root)

        # fnmatch 区分大小写, 统一转小写匹配
        pattern_lower = pattern.lower() if pattern else None

        matches: list[tuple[str, int]] = []  # (path, size)
        truncated = False
        root_path = root
        root_str = str(root_path)
        for dirpath, dirnames, filenames in os.walk(root_path):
            rel_depth = 0 if dirpath == root_str else dirpath[len(
                root_str):].count(os.sep) + 1
            if rel_depth > max_depth:
                dirnames[:] = []
                continue
            # 原地剪枝 skip 目录
            dirnames[:] = [
                d for d in dirnames if d not in self._AI_SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                if fn.startswith("."):
                    continue
                if pattern_lower is not None:
                    if not fnmatch.fnmatch(fn.lower(), pattern_lower):
                        continue
                full = os.path.join(dirpath, fn)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                matches.append((full, size))
                if len(matches) >= max_results:
                    truncated = True
                    break
            if truncated:
                break

        if not matches:
            if pattern:
                return _("在 %s 下未找到匹配 '%s' 的文件") % (root, pattern)
            return _("%s 下没有可列出的文件") % str(root)

        # 按路径排序, 截断
        matches.sort(key=lambda x: x[0])
        shown = matches[:max_results]
        lines = [f"Found {len(matches)} file(s) under {root}"]
        if pattern:
            lines[0] += f" matching '{pattern}'"
        if truncated:
            lines[0] += f" (showing first {len(shown)})"
        lines.append("")
        for p, size in shown:
            # 路径相对工作目录展示更紧凑
            try:
                rel = os.path.relpath(p, root_str)
            except ValueError:
                rel = p
            lines.append(f"  {rel}  ({size} bytes)")

        return "\n".join(lines)

    # ==================================================================
    # AI 工具: read_file - 读取文件内容供 agent 检视
    # ==================================================================
    # 探测二进制文件: 读 8KB 抽样, 出现 NUL 字节就视为二进制.
    _AI_BINARY_SNIFF_BYTES = 8192

    def _ai_read_file(self, args: dict) -> str:
        path_str = (args.get("path") or "").strip()
        if not path_str:
            return _("错误: path 不能为空")
        path = Path(path_str).expanduser()
        if not path.exists():
            return _("错误: 文件不存在: %s") % path_str
        if not path.is_file():
            return _("错误: 不是普通文件: %s") % path_str

        try:
            start_line = int(args.get("start_line") or 1)
        except (TypeError, ValueError):
            start_line = 1
        try:
            max_lines = int(args.get("max_lines") or 500)
        except (TypeError, ValueError):
            max_lines = 500
        try:
            max_bytes = int(args.get("max_bytes") or 102400)
        except (TypeError, ValueError):
            max_bytes = 102400
        start_line = max(1, start_line)
        max_lines = max(1, min(max_lines, 2000))
        max_bytes = max(1024, min(max_bytes, 524288))

        # 二进制嗅探
        try:
            with path.open("rb") as f:
                sniff = f.read(self._AI_BINARY_SNIFF_BYTES)
        except OSError as e:
            return _("错误: 读取失败: %s") % e
        if b"\x00" in sniff:
            return _("错误: 文件看起来是二进制, 不支持读取: %s") % path_str

        try:
            size = path.stat().st_size
        except OSError:
            size = 0

        # 一次性把窗口内文本读出来, 之后按行切.
        # 先按字节上限粗略估算要读多少
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                # 跳过 start_line-1 行
                for _i in range(start_line - 1):
                    f.readline()
                buf = f.read(max_bytes + 4096)  # 多读一点以凑整行
        except OSError as e:
            return _("错误: 读取失败: %s") % e

        lines = buf.splitlines()
        truncated_by_bytes = False
        if len(buf) > max_bytes:
            # 按字节回退, 找最后一个不超限的换行
            truncated_by_bytes = True
            acc = 0
            cut = 0
            for ln in lines:
                next_acc = acc + len(ln.encode("utf-8")) + 1
                if next_acc > max_bytes:
                    break
                acc = next_acc
                cut += 1
            lines = lines[:cut]

        if len(lines) > max_lines:
            lines = lines[:max_lines]
            truncated_by_lines = True
        else:
            truncated_by_lines = False

        truncated = truncated_by_bytes or truncated_by_lines
        width = len(str(start_line + len(lines) - 1)
                    ) if lines else len(str(start_line))
        out: list[str] = []
        out.append(f"--- {path} (size: {size} bytes) ---")
        for i, ln in enumerate(lines):
            out.append(f"{start_line + i:>{width}}  {ln}")
        if truncated:
            more_lines = ""
            if truncated_by_lines:
                more_lines = _("更多行请用 start_line / max_lines 分段读取")
            if truncated_by_bytes:
                more_lines = (
                    more_lines + "; " if more_lines else "") + _("内容被 max_bytes 截断")
            out.append(f"… ({more_lines})")
        return "\n".join(out)

    # ==================================================================
    # AI 工具: list_items - 自查当前编排列表内容
    # ==================================================================
    def _ai_list_items(self, args: dict) -> str:
        kind_raw = (args.get("kind") or "").strip().lower()
        kind: str | None = None
        if kind_raw in ("file", "text"):
            kind = kind_raw
        elif kind_raw and kind_raw not in ("", "all", "any"):
            return _("错误: kind 必须是 'file' 或 'text', 得到: %s") % kind_raw
        try:
            max_items = int(args.get("max_items") or 100)
        except (TypeError, ValueError):
            max_items = 100
        max_items = max(1, min(max_items, 500))

        all_items = self.engine.items
        if not all_items:
            return _("编排列表为空 (0 项)")

        file_total = sum(1 for it in all_items if it.type == "file")
        text_total = sum(1 for it in all_items if it.type == "text")
        header = (
            f"Orchestration list: {len(all_items)} item(s) total "
            f"({file_total} file, {text_total} text)"
        )

        # 过滤出要展示的 (index, item) 对
        shown: list[tuple[int, object]] = []
        for idx, it in enumerate(all_items):
            if kind == "file" and it.type != "file":
                continue
            if kind == "text" and it.type != "text":
                continue
            shown.append((idx, it))

        if kind:
            header += f", showing {len(shown)} {kind} item(s)"

        if not shown:
            return header + "\n" + _("(无匹配项)")

        truncated = len(shown) > max_items
        shown = shown[:max_items]
        width = len(str(len(all_items) - 1)) if all_items else 1
        lines = [header, ""]
        for i, it in shown:
            if it.type == "file":
                p = it.path or ""
                name = os.path.basename(p) or p
                tag = "abs" if it.force_absolute else "rel"
                lines.append(f"  [{i:>{width}}] file({tag}): {name}  —  {p}")
            else:
                content = it.content or ""
                preview = content[:60].replace("\n", " ")
                if len(content) > 60:
                    preview += "…"
                lines.append(f"  [{i:>{width}}] text: {preview}")
        if truncated:
            lines.append(_("… 仅显示前 %d 项, 完整列表请用 kind 过滤") % max_items)
        return "\n".join(lines)

    # ==================================================================
    # 插入文字 (含常用语支持)
    # ==================================================================
    def insert_text(self, above: bool = True):
        current_row = self.list_widget.currentRow()
        if current_row == -1:
            index = len(self.engine.items)
        else:
            index = current_row if above else current_row + 1

        dialog = TextEditDialog(
            self, _("插入自定义文字"),
            show_phrases_button=True, common_phrases=self.common_phrases,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        text = dialog.get_text()
        if not text:
            return
        self._push_undo()
        self.engine.add_text(text, index=index)
        self._refresh_list()
        self.list_widget.setCurrentRow(index)
        self.status_bar.showMessage(_("已插入文字"))
        self._show_toast(_("已插入文字"))

    # ==================================================================
    # 撤销 / 重做
    # ==================================================================
    def _push_undo(self):
        if self._loading_state:
            return
        self.undo_manager.push(UndoState(
            self.engine.items,
            self.engine.checked_paths,
            self.engine.use_absolute,
            self.engine.show_header,
        ))
        self._update_button_states()

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

    def _restore_state(self, state: UndoState):
        self._loading_state = True
        try:
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
                self._update_tree_ancestors()

            self._refresh_list()
        finally:
            self._loading_state = False
        self._update_button_states()

    def _uncheck_all_tree(self):
        def walk(item):
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(0, Qt.Unchecked)
            for i in range(item.childCount()):
                walk(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def _show_toast(self, text: str, duration: int | None = None):
        if duration is None:
            duration = ToastNotification.DEFAULT_DURATION
        ToastNotification.show_toast(text, self, duration)

    # ==================================================================
    # 关闭事件
    # ==================================================================
    def closeEvent(self, event):
        if hasattr(self, "ai_panel") and self.ai_panel is not None:
            self.ai_panel.shutdown()
        if self.ipc_stop:
            self.ipc_stop()
        if self.engine.items:
            reply = QMessageBox.question(
                self, _("确认退出"),
                _("编排列表不为空，确定退出吗？"),
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
        event.accept()
