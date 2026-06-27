"""Flet 版本主视图 - 三栏布局"""

from __future__ import annotations

import fnmatch
import os
import threading
import time
from pathlib import Path
from typing import Optional

import flet as ft

from filecollector.engine import FileCollectorEngine
from filecollector.models import ItemData
from filecollector.utils import safe_read_file, display_path, debounce, is_binary_file
from filecollector.i18n import _, add_listener, remove_listener
from filecollector.config import (
    load_settings, save_settings,
    get_allowed_binary_extensions,
)
from filecollector.gui_flet.file_tree import FileTreePanel
from filecollector.gui_flet.git_history import GitHistoryPanel
from filecollector.gui_flet.arrangement_list import ArrangementListPanel
from filecollector.gui_flet.preview_panel import PreviewPanel
from filecollector.gui_flet.ai_panel import AIPanel
from filecollector.gui_flet.ai_settings_dialog import (
    load_ai_settings, AISettingsDialog,
)
from filecollector.gui_flet.dialogs import (
    PhrasesDialog, ShortcutsDialog, TextEditDialog
)
from filecollector.gui_flet.preprocess_runner import PreprocessRunner
from filecollector.gui_flet.buttons import (
    primary_btn, secondary_btn, icon_btn,
)
from filecollector.gui_flet.snack import show_snack
from filecollector.gui_flet.undo import UndoManager
from filecollector.gui_flet.vlm_queue import VLMQueueManager
from filecollector.git_service import sanitize_git_error, is_git_repo


class MainView:
    """主视图容器 - 三栏卡片式布局"""

    def __init__(self, page: ft.Page):
        self.page = page
        self.engine = FileCollectorEngine()
        self.undo_manager = UndoManager()
        self.common_phrases: list[str] = []

        # 共享文件选择器（避免每次创建新实例导致超时）
        # FilePicker 继承自 Service, 必须添加到 page.services (非 overlay),
        # 否则 Flutter 运行时报 "Unknown control: FilePicker"
        self._file_picker = ft.FilePicker()
        self.page.services.append(self._file_picker)
        self.page.update()

        # 加载常用语
        if hasattr(self.engine, "load_common_phrases_from_disk"):
            self.engine.load_common_phrases_from_disk()
            self.common_phrases = list(self.engine.common_phrases)

        # Git 模式状态
        self.is_git_mode = False

        # 修饰键状态 (Ctrl/Shift) 供多选使用.
        # Flet 的点击事件不暴露 modifier keys, 需要通过键盘事件跟踪.
        # 默认 False; 页面/面板级别的键盘监听器会在按键按下/释放时更新它们.
        self._ctrl_held: bool = False
        self._shift_held: bool = False

        # 构建 UI
        self._build_ui()

        # 语言切换监听
        add_listener(self._on_language_changed)

        # 键盘快捷键
        self.page.on_keyboard_event = self._on_keyboard

        # 窗口最小宽度强制（Linux/GTK 上 min_width 不一定生效）
        self._min_width = 1100
        self._resize_guard = False
        self.page.on_resize = self._on_resize
        # 拦截原生窗口关闭事件，防止 Flet 默认清理逻辑卡死
        self.page.on_window_event = self._on_window_event

        # 崩溃恢复: 启动时检查未保存会话
        self._check_recovery_on_startup()

    def _on_keyboard(self, e: ft.KeyboardEvent):
        """处理键盘快捷键"""
        key = e.key.upper()
        ctrl = e.ctrl
        shift = e.shift
        # 跟踪 Ctrl / Shift 键状态供多选 (列表 + Git 提交) 使用
        # Flet 的 ControlEvent 不暴露 modifier keys, 必须通过 KeyboardEvent 全局跟踪
        self._ctrl_held = ctrl
        self._shift_held = shift

        has_work_dir = self.engine.work_dir is not None
        has_items = len(self.engine.items) > 0

        if ctrl and key == "Z" and not shift:
            # 撤销栈空时与按钮保持一致: 忽略 (no-op, 不弹 snack 避免噪音)
            if self.undo_manager.can_undo:
                self._on_undo(None)
        elif ctrl and key == "Z" and shift:
            if self.undo_manager.can_redo:
                self._on_redo(None)
        elif ctrl and key == "O":
            self._on_load_project(None)
        elif ctrl and key == "S" and not shift:
            # 工作目录未设置时, 跟菜单项保持一致: 忽略并提示
            if not has_work_dir:
                show_snack(self.page, _("尚未设置工作目录"))
            else:
                self._on_save_project(None)
        elif ctrl and key == "S" and shift:
            if not has_work_dir:
                show_snack(self.page, _("尚未设置工作目录"))
            else:
                self._on_save_project_as(None)
        elif ctrl and key == "E":
            self.arrangement_panel._on_add_external(None)
        elif ctrl and key == "I" and not shift:
            self.arrangement_panel._on_insert_text_above(None)
        elif ctrl and key == "I" and shift:
            self.arrangement_panel._on_insert_text_below(None)
        elif ctrl and key == "N":
            # 清空需要列表非空
            if not has_items:
                return
            self.arrangement_panel._on_clear(None)
        elif ctrl and key == "G":
            # 生成 TXT 需要工作目录 + 列表非空
            if not (has_work_dir and has_items):
                return
            self.arrangement_panel._on_generate_txt(None)
        elif ctrl and key == "C" and shift:
            # 生成到剪贴板需要工作目录 + 列表非空
            if not (has_work_dir and has_items):
                return
            self.arrangement_panel._on_generate_clipboard(None)
        elif ctrl and key == ",":
            self._on_ai_settings(None)
        elif ctrl and key == "/":
            self._on_shortcuts(None)
        elif ctrl and key == "F" and shift:
            self._on_global_search(None)
        elif key == "F1":
            self._on_about(None)

    def _build_ui(self):
        """构建三栏布局"""
        # 左侧文件树面板
        self.file_tree_panel = FileTreePanel(self)

        # 左侧 Git 历史面板 (默认隐藏)
        self.git_history_panel = GitHistoryPanel(self)

        # 中间编排列表面板
        self.arrangement_panel = ArrangementListPanel(self)

        # 右侧预览面板
        self.preview_panel = PreviewPanel(self)

        # AI 面板（默认隐藏）
        self.ai_panel = AIPanel(self)
        self.ai_panel.template_triggered = self._on_template_triggered

        # VLM 预处理 runner (编排列表新增 / 移除 binary 条目后触发)
        self.preprocess_runner = PreprocessRunner(
            main_view=self,
            get_work_dir=self._get_work_dir_for_preprocess,
            get_allowed_exts=self._get_allowed_binary_exts,
            on_status=self._on_preprocess_status,
            on_preview=self._on_preprocess_preview,
        )

        # VLM 预处理队列 (并发控制 + 暂停/取消)
        self.vlm_queue = VLMQueueManager(max_concurrency=3)
        self.vlm_queue.set_executor(self.preprocess_runner.vlm_task_executor)
        self.vlm_queue.on_progress = self._on_vlm_progress_changed
        self.vlm_queue.on_state_changed = self._on_vlm_state_changed
        self.vlm_queue.on_item_cancelled = self.preprocess_runner.on_item_cancelled
        self.preprocess_runner.vlm_queue = self.vlm_queue
        self._vlm_progress_card = self._build_vlm_progress_card()

        # 左栏容器 (文件树 / Git 历史切换)
        self.left_panel_container = ft.Container(
            content=self.file_tree_panel.container,
            expand=True,
        )

        # 三栏分割器
        self.main_row = ft.Row(
            [
                self.left_panel_container,
                self.arrangement_panel.container,
                self.preview_panel.container,
            ],
            spacing=8,
            expand=True,
        )

        # 主内容区 + VLM 进度卡片悬浮层
        self._main_content = ft.Container(
            content=self.main_row,
            expand=True,
            padding=ft.Padding(left=8, right=8, top=0, bottom=8),
        )

        # 空状态引导: 未设置工作目录 / Git 模式无提交时覆盖主内容区
        self._empty_state_view = self._build_empty_state()
        self._git_empty_state_view = self._build_git_empty_state()
        self._main_stack = ft.Stack(
            [self._main_content, self._vlm_progress_card,
             self._empty_state_view, self._git_empty_state_view],
            expand=True,
        )

        # 主容器
        self.container = ft.Container(
            content=ft.Column(
                [
                    self._build_app_bar(),
                    ft.Container(
                        content=self._main_stack,
                        expand=True,
                    ),
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
        )

    def _build_empty_state(self) -> ft.Container:
        """未设置工作目录时的引导界面 (覆盖主内容区)."""
        self._empty_open_btn = primary_btn(
            _("打开工作目录"),
            icon=ft.Icons.FOLDER_OPEN,
            on_click=self._on_open_folder,
        )
        return ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.FOLDER_OPEN, size=72,
                            color=ft.Colors.GREY_400),
                    ft.Container(
                        content=ft.Text(
                            _("未选择工作目录"),
                            size=20, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.GREY_700,
                        ),
                        margin=ft.Margin(top=8, bottom=4, left=0, right=0),
                    ),
                    ft.Text(
                        _("打开一个文件夹作为工作目录，即可开始收集与编排文件。"),
                        size=13, color=ft.Colors.GREY_600,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Container(
                        content=self._empty_open_btn,
                        margin=ft.Margin(top=20, bottom=0, left=0, right=0),
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
            ),
            alignment=ft.alignment.Alignment(0, 0),
            expand=True,
            visible=False,
        )

    def _build_git_empty_state(self) -> ft.Container:
        """Git 模式无提交记录 / 非 Git 仓库时的引导界面 (覆盖主内容区).

        对齐 GNOME 版 ab245ab 的 git_empty_page_widget (图标 xsi-git-symbolic):
        - 非 Git 仓库: 「未检测到 Git 仓库」
        - 是仓库但无提交: 「暂无提交记录」
        文案在 _configure_git_empty_page 中按当前仓库状态动态设置.
        """
        self._git_empty_title = ft.Text(
            _("暂无提交记录"),
            size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_700,
        )
        self._git_empty_desc = ft.Text(
            _("当前 Git 仓库中还没有任何提交。完成首次 git commit 后，提交历史将显示在此处。"),
            size=13, color=ft.Colors.GREY_600,
            text_align=ft.TextAlign.CENTER,
        )
        return ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.COMMIT, size=72, color=ft.Colors.GREY_400),
                    ft.Container(
                        content=self._git_empty_title,
                        margin=ft.Margin(top=8, bottom=4, left=0, right=0),
                    ),
                    self._git_empty_desc,
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
            ),
            alignment=ft.alignment.Alignment(0, 0),
            expand=True,
            visible=False,
        )

    def _build_app_bar(self) -> ft.Control:
        """构建顶部应用栏 (使用 Container 替代 AppBar, 避免 Material 3 滚动阴影)"""
        # Git 切换按钮 (实例变量, 方便修改图标/tooltip)
        # 默认 disabled: 由 _update_toolbar_states 在有工作目录时启用
        self.btn_toggle_git = icon_btn(
            icon=ft.Icons.ALT_ROUTE,
            tooltip=_("切换到 Git 提交历史"),
            on_click=self._on_toggle_git,
            disabled=True,
            disabled_color=ft.Colors.GREY_400,
        )

        # 撤销/重做按钮: 由 _update_toolbar_states 维护 disabled
        self.btn_undo = icon_btn(
            icon=ft.Icons.UNDO,
            tooltip=_("撤销") + " (Ctrl+Z)",
            on_click=self._on_undo,
            disabled=True,
            disabled_color=ft.Colors.GREY_400,
        )
        self.btn_redo = icon_btn(
            icon=ft.Icons.REDO,
            tooltip=_("重做") + " (Ctrl+Shift+Z)",
            on_click=self._on_redo,
            disabled=True,
            disabled_color=ft.Colors.GREY_400,
        )
        # 全局搜索: 由 _update_toolbar_states 在有工作目录时启用
        self.btn_global_search = icon_btn(
            icon=ft.Icons.SEARCH,
            tooltip=_("全局内容搜索") + " (Ctrl+Shift+F)",
            on_click=self._on_global_search,
            disabled=True,
            disabled_color=ft.Colors.GREY_400,
        )
        # 左侧操作 (空状态下整体隐藏, 仅保留右侧三点菜单)
        self._toolbar_leading = ft.Row(
            [
                primary_btn(
                    _("打开文件夹"),
                    icon=ft.Icons.FOLDER_OPEN,
                    on_click=self._on_open_folder,
                ),
                self.btn_undo,
                self.btn_redo,
                ft.VerticalDivider(),
                self.btn_toggle_git,
                self.btn_global_search,
            ],
            spacing=0,
        )
        # 右侧: AI 切换按钮 (空状态下隐藏)
        self._btn_ai_toggle = icon_btn(
            icon=ft.Icons.SMART_TOY,
            tooltip=_("AI 助手"),
            on_click=self._on_toggle_ai,
            padding=0,
        )

        # 标题
        title = ft.Text(
            _("当前工作目录: 未设置"),
            size=14,
            weight=ft.FontWeight.W_600,
            color=ft.Colors.BLUE_600,
        )
        self.work_dir_label = title

        # 右侧操作
        # 先把需要按工作目录启用/禁用的菜单项挂到 self 上,
        # 后面 _update_subtitle 会同步切换它们的 disabled。
        self.menu_save_project = ft.PopupMenuItem(
            content=ft.Text(_("保存项目")),
            icon=ft.Icons.SAVE,
            on_click=self._on_save_project,
        )
        self.menu_save_project_as = ft.PopupMenuItem(
            content=ft.Text(_("项目另存为...")),
            icon=ft.Icons.SAVE_AS,
            on_click=self._on_save_project_as,
        )
        self.menu_clear_cache = ft.PopupMenuItem(
            content=ft.Text(_("清除工作区缓存")),
            icon=ft.Icons.CLEANING_SERVICES,
            on_click=self._on_clear_cache,
        )
        self._toolbar_actions = ft.Row(
            [
                self._btn_ai_toggle,
                ft.PopupMenuButton(
                    icon=ft.Icons.MORE_VERT,
                    padding=0,
                    items=[
                        self.menu_save_project,
                        self.menu_save_project_as,
                        ft.PopupMenuItem(
                            content=ft.Text(_("打开项目")),
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=self._on_load_project,
                        ),
                        ft.PopupMenuItem(),  # 分隔符
                        ft.PopupMenuItem(
                            content=ft.Text(_("常用语管理")),
                            icon=ft.Icons.CHAT,
                            on_click=self._on_phrases,
                        ),
                        ft.PopupMenuItem(
                            content=ft.Text(_("场景模板管理")),
                            icon=ft.Icons.DASHBOARD_CUSTOMIZE,
                            on_click=self._on_templates,
                        ),
                        ft.PopupMenuItem(
                            content=ft.Text(_("偏好设置")),
                            icon=ft.Icons.SETTINGS,
                            on_click=self._on_ai_settings,
                        ),
                        ft.PopupMenuItem(),  # 分隔符
                        self.menu_clear_cache,
                        ft.PopupMenuItem(),  # 分隔符
                        ft.PopupMenuItem(
                            content=ft.Text(_("键盘快捷键")),
                            icon=ft.Icons.KEYBOARD,
                            on_click=self._on_shortcuts,
                        ),
                        ft.PopupMenuItem(
                            content=ft.Text(_("关于")),
                            icon=ft.Icons.INFO,
                            on_click=self._on_about,
                        ),
                    ],
                ),
            ],
            spacing=0,
        )

        return ft.Container(
            content=ft.Row(
                [
                    self._toolbar_leading,
                    ft.Container(
                        content=title,
                        alignment=ft.Alignment(0, 0),
                        expand=True,
                    ),
                    self._toolbar_actions,
                ],
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=8, top=4, right=8, bottom=4),
            bgcolor=ft.Colors.SURFACE,
            height=56,
        )

    def initialize(self):
        """初始化视图状态"""
        self.file_tree_panel.refresh()
        self.arrangement_panel.refresh()
        self._update_subtitle()
        self._update_toolbar_states()

    def _on_language_changed(self, lang: str):
        """语言切换时重新构建 UI"""
        old = self.container
        self._build_ui()
        idx = self.page.controls.index(old) if old in self.page.controls else 0
        self.page.controls[idx] = self.container
        self.initialize()
        self.page.update()

    # ==================================================================
    # 事件处理
    # ==================================================================

    def _on_undo(self, e):
        """撤销"""
        state = self.undo_manager.undo(self.engine.snapshot())
        if state:
            self.engine.restore(state)
            self._refresh_all()

    def _on_redo(self, e):
        """重做"""
        state = self.undo_manager.redo(self.engine.snapshot())
        if state:
            self.engine.restore(state)
            self._refresh_all()

    def _on_open_folder(self, e):
        """打开工作目录"""

        async def pick():
            path = await self._file_picker.get_directory_path(
                dialog_title=_("选择工作文件夹")
            )
            if path:
                self._push_undo()
                self.engine.work_dir = Path(path).resolve()
                self.engine.items.clear()
                self.engine.checked_paths.clear()
                self.file_tree_panel.set_work_dir(self.engine.work_dir)
                self._update_subtitle()
                self.arrangement_panel.refresh()
                self._update_toolbar_states()

                # 若当前处于 Git 模式, 重新加载 Git 日志和按钮状态
                if self.is_git_mode:
                    self.git_history_panel.load_git_history(
                        str(self.engine.work_dir))
                    self.arrangement_panel._update_button_states()

                show_snack(self.page, _("已设置工作目录: %s") % self.engine.work_dir)

        self.page.run_task(pick)

    def _on_resize(self, e):
        """强制窗口最小宽度"""
        if self._resize_guard:
            return
        if self.page.window.width < self._min_width:
            self._resize_guard = True
            try:
                self.page.window.width = self._min_width
                self.page.update()
            finally:
                self._resize_guard = False
        # 通知 AI 面板防抖重绘气泡, 修正宽度估算偏差导致的裁切
        if self.ai_panel.container in self.main_row.controls:
            self.ai_panel.handle_page_resize()

    def _on_toggle_ai(self, e):
        """切换 AI 面板"""
        if self.ai_panel.container in self.main_row.controls:
            self.main_row.controls.remove(self.ai_panel.container)
            self._min_width = 1100
            self.page.window.min_width = 1100
        else:
            self.main_row.controls.append(self.ai_panel.container)
            self._min_width = 1420
            self.page.window.min_width = 1420
            if self.page.window.width < 1420:
                self.page.window.width = 1420
        self.page.update()

    # ==================================================================
    # Git 模式
    # ==================================================================

    def _on_toggle_git(self, e):
        """切换文件树 / Git 提交历史模式."""
        self.is_git_mode = not self.is_git_mode

        if self.is_git_mode:
            self.left_panel_container.content = self.git_history_panel.container
            self.btn_toggle_git.icon = ft.Icons.FOLDER_OPEN
            self.btn_toggle_git.tooltip = _("切换到文件树")
            self.arrangement_panel.set_git_mode(True)

            # 首次切换时自动加载 Git 日志 (无 work_dir 时会隐藏搜索框)
            if not self.git_history_panel._commits:
                self.git_history_panel.load_git_history(
                    str(self.engine.work_dir) if self.engine.work_dir else "")
            # 切到 Git 模式时让 Git 历史面板的键盘监听器获得焦点,
            # 这样 Ctrl/Shift 修饰键才能被正确跟踪.
            self.git_history_panel._ensure_keyboard_focus()
        else:
            self.left_panel_container.content = self.file_tree_panel.container
            self.btn_toggle_git.icon = ft.Icons.ALT_ROUTE
            self.btn_toggle_git.tooltip = _("切换到 Git 提交历史")
            self.arrangement_panel.set_git_mode(False)
            # 切回文件树模式时焦点交还编排列表面板.
            self.arrangement_panel._ensure_keyboard_focus()

        # 切换模式后重新评估空状态 (Git 模式 + 无提交时显示 git 空状态)
        self._refresh_empty_state()
        self.page.update()

    def on_git_commit_selected(self, commit):
        """Git 历史面板选中 commit 后, 在预览区渲染 diff."""
        if not self.engine.work_dir:
            return
        self.preview_panel.show_raw_text(_("正在加载 Diff..."))
        self.arrangement_panel.set_git_export_enabled(True)

        import threading

        def _load():
            try:
                from filecollector.git_service import get_commit_diff
                diff_text = get_commit_diff(
                    str(self.engine.work_dir), commit.hash)
                error = None
            except Exception as ex:
                diff_text = ""
                error = str(ex)

            self.page.run_task(
                self._on_commit_diff_loaded,
                commit, diff_text, error,
            )

        thread = threading.Thread(target=_load, daemon=True)
        thread.start()

    async def _on_commit_diff_loaded(self, commit, diff_text, error):
        if error:
            self.preview_panel.show_raw_text(
                _("加载 Diff 失败: %s") % sanitize_git_error(str(error)))
        else:
            title = f"Commit: {commit.short_hash} - {commit.message}"
            self.preview_panel.show_diff(title, diff_text)

    def on_git_add_all_changed(self, e=None):
        """一键添加所有改动文件到编排列表."""
        if not self.engine.work_dir:
            from filecollector.gui_flet.snack import show_snack
            show_snack(self.page, _("请先设置工作目录"))
            return

        import threading

        def _do():
            try:
                from filecollector.git_service import (
                    get_status, parse_status_files)
                status = get_status(str(self.engine.work_dir))
                if not status.strip():
                    self.page.run_task(self._git_snack,
                                       _("当前工作区没有未提交的改动"))
                    return

                files = parse_status_files(
                    status, str(self.engine.work_dir))
                if not files:
                    self.page.run_task(self._git_snack,
                                       _("没有可添加的文件"))
                    return

                self.page.run_task(self._apply_git_add_files, files)
            except Exception as ex:
                self.page.run_task(self._git_snack,
                                   _("Git 错误: %s") % sanitize_git_error(str(ex)))

        thread = threading.Thread(target=_do, daemon=True)
        thread.start()

    async def _apply_git_add_files(self, files: list):
        """在 UI 线程中将 git 变更文件加入编排列表."""
        self._push_undo()
        added = 0
        for path in files:
            if not self._path_in_items(path):
                self.engine.add_file(path, force_absolute=False)
                self.file_tree_panel.checked_paths.add(path)
                added += 1

        self.file_tree_panel.refresh()
        self.arrangement_panel.refresh()
        # 触发二进制预处理
        runner = getattr(self, "preprocess_runner", None)
        if runner:
            try:
                runner.reevaluate_queue()
            except Exception:
                pass

    async def _git_snack(self, text: str):
        """异步显示 Git 操作的 SnackBar (供 page.run_task 调用)."""
        show_snack(self.page, text)

    def _path_in_items(self, path: str) -> bool:
        """检查路径是否已在编排列表中."""
        for it in self.engine.items:
            if it.type == "file" and it.path == path:
                return True
        return False

    def on_git_export_working_diff(self, e=None):
        """导出工作区 Diff 到编排列表."""
        if not self.engine.work_dir:
            show_snack(self.page, _("请先设置工作目录"))
            return

        import threading

        def _do():
            try:
                from filecollector.git_service import get_working_tree_diff
                diff = get_working_tree_diff(str(self.engine.work_dir))
                if not diff.strip():
                    self.page.run_task(self._git_snack,
                                       _("当前工作区没有未提交的改动"))
                    return
                self.page.run_task(
                    self._apply_git_export_diff, diff, "working")
            except Exception as ex:
                self.page.run_task(self._git_snack,
                                   _("Git 错误: %s") % sanitize_git_error(str(ex)))

        thread = threading.Thread(target=_do, daemon=True)
        thread.start()

    def on_git_export_commit_diff(self, e=None):
        """导出选中 Commit 的 Diff 到编排列表 (支持多选).

        selected_commits 按 _filtered_commits 顺序返回 (最新在前);
        依次在位置 0 插入, 最终列表为提交先后顺序 (最旧在前).
        """
        commits = list(self.git_history_panel.selected_commits)
        if not commits or not self.engine.work_dir:
            return

        import threading

        def _do():
            try:
                from filecollector.git_service import get_commit_diff
                # 依次获取每个 commit 的 diff, 在 UI 线程插入
                results: list[tuple[str, str, str]] = []  # (hash, short, message)
                for commit in commits:
                    diff = get_commit_diff(
                        str(self.engine.work_dir), commit.hash)
                    results.append((diff, commit.short_hash, commit.message))
                self.page.run_task(
                    self._apply_multi_commit_diff, results)
            except Exception as ex:
                self.page.run_task(self._git_snack,
                                   _("Git 错误: %s") % sanitize_git_error(str(ex)))

        thread = threading.Thread(target=_do, daemon=True)
        thread.start()

    async def _apply_multi_commit_diff(
        self, results: list[tuple[str, str, str]],
    ):
        """在 UI 线程中将多个 commit diff 按选中顺序插入编排列表.

        results: [(diff, short_hash, message), ...] 按 selected_commits 顺序
        (最新在前). 依次在位置 0 插入, 最终列表为提交先后顺序 (最旧在前),
        对齐 GNOME 版 on_git_export_commit_diff (window.vala:2203).
        """
        from filecollector.models import ItemData
        from filecollector.gui_flet.snack import show_snack

        self._push_undo()
        for diff, short_hash, message in results:
            md_text = (
                f"# Git Commit: {short_hash} ({message})\n\n"
                f"```diff\n{diff}\n```"
            )
            self.engine.items.insert(0, ItemData("text", content=md_text))
        self.arrangement_panel.refresh()

    async def _apply_git_export_diff(
        self, diff: str, mode: str,
        short_hash: str = "", message: str = "",
    ):
        """在 UI 线程中将单个 diff (工作区或单 commit) 插入编排列表."""
        from filecollector.models import ItemData
        from filecollector.gui_flet.snack import show_snack

        self._push_undo()
        if mode == "commit":
            md_text = (
                f"# Git Commit: {short_hash} ({message})\n\n"
                f"```diff\n{diff}\n```"
            )
        else:
            md_text = f"# Git Working Tree Diff\n\n```diff\n{diff}\n```"

        self.engine.items.insert(
            0, ItemData("text", content=md_text))
        self.arrangement_panel.refresh()

    def _on_save_project(self, e):
        """保存项目 (若有已保存路径则直接覆盖, 否则另存为)."""
        if getattr(self.engine, "project_file", None):
            try:
                self.engine.common_phrases = list(self.common_phrases)
                self.engine.save_project(self.engine.project_file)
                show_snack(self.page, _("项目已保存: %s") %
                           self.engine.project_file)
                self._clear_recovery()
            except Exception as ex:
                show_snack(self.page, _("保存失败: %s") % ex)
            return
        self._on_save_project_as(e)

    def _on_load_project(self, e):
        """加载项目"""

        async def pick():
            files = await self._file_picker.pick_files(
                dialog_title=_("打开项目"),
                allowed_extensions=["json", "fcol"],
            )
            if files:
                try:
                    self.engine.load_project(files[0].path)
                    self.common_phrases = list(self.engine.common_phrases)
                    # _refresh_all 内部会同步 checked_paths
                    self._refresh_all()
                    show_snack(self.page, _("项目已加载: %s") % files[0].path)
                    self._clear_recovery()
                except Exception as ex:
                    show_snack(self.page, _("加载失败: %s") % ex)

        self.page.run_task(pick)

    def _on_ai_settings(self, e):
        """打开偏好设置"""
        dlg = AISettingsDialog(self)
        self.page.show_dialog(dlg)

    def _on_save_project_as(self, e):
        """项目另存为"""
        async def pick():
            path = await self._file_picker.save_file(
                dialog_title=_("保存项目到"),
                file_name="project.fcol",
            )
            if path:
                if not path.endswith(".fcol"):
                    path += ".fcol"
                try:
                    self.engine.common_phrases = list(self.common_phrases)
                    self.engine.save_project(path)
                    show_snack(self.page, _("项目已保存: %s") % path)
                    self._clear_recovery()
                except Exception as ex:
                    show_snack(self.page, _("保存失败: %s") % ex)

        self.page.run_task(pick)

    def _on_window_event(self, e):
        """拦截窗口关闭事件 (点击右上角 X)."""
        if e.data == "close":
            try:
                self.page.window.prevent_close = True
            except Exception:
                pass

            if self.engine.items:
                def on_confirm(ev):
                    if ev.control.data == "yes":
                        self.page.pop_dialog()
                        self._force_exit()
                    else:
                        self.page.pop_dialog()
                        try:
                            self.page.window.prevent_close = False
                        except Exception:
                            pass

                dlg = ft.AlertDialog(
                    title=ft.Text(_("确认退出")),
                    content=ft.Text(_("编排列表不为空，确定退出吗？")),
                    actions=[
                        secondary_btn(_("取消"), on_click=on_confirm, data="no"),
                        primary_btn(
                            _("确定"), on_click=on_confirm, data="yes"),
                    ],
                )
                self.page.show_dialog(dlg)
            else:
                self._force_exit()

    def _on_quit(self, e):
        """退出应用 (列表非空时确认)."""
        if self.engine.items:
            def on_confirm(ev):
                if ev.control.data == "yes":
                    self.page.pop_dialog()
                    self._force_exit()
                else:
                    self.page.pop_dialog()

            dlg = ft.AlertDialog(
                title=ft.Text(_("确认退出")),
                content=ft.Text(_("编排列表不为空，确定退出吗？")),
                actions=[
                    secondary_btn(_("取消"), on_click=on_confirm, data="no"),
                    primary_btn(_("确定"), on_click=on_confirm, data="yes"),
                ],
            )
            self.page.show_dialog(dlg)
        else:
            self._force_exit()

    def _force_exit(self):
        """强制退出进程."""
        # 停止 VLM 队列
        if hasattr(self, "vlm_queue") and self.vlm_queue:
            self.vlm_queue.cancel()
        import os
        os._exit(0)

    def _on_phrases(self, e):
        """打开常用语管理"""
        dlg = PhrasesDialog(self)
        self.page.show_dialog(dlg)

    def _on_templates(self, e):
        """打开场景模板管理"""
        from filecollector.gui_flet.templates_manager import TemplatesManagerDialog
        dlg = TemplatesManagerDialog(self)
        self.page.show_dialog(dlg)

    def _on_global_search(self, e):
        """打开全局内容搜索"""
        if not self.engine.work_dir:
            show_snack(self.page, _("请先设置工作目录"))
            return
        from filecollector.gui_flet.global_search_dialog import GlobalSearchDialog
        dlg = GlobalSearchDialog(self)
        self.page.show_dialog(dlg)

    def _on_template_triggered(self, header: str, footer: str) -> None:
        """AI 面板触发模板: 在编排列表头尾插入占位文本."""
        self._push_undo()
        from filecollector.models import ItemData
        if header and header.strip():
            self.engine.items.insert(0, ItemData("text", content=header))
        if footer and footer.strip():
            self.engine.items.append(ItemData("text", content=footer))
        self.arrangement_panel.refresh()

    def _on_ai_toc(self) -> None:
        """AI 生成阅读指南."""
        if not self.engine.items:
            show_snack(self.page, _("编排列表为空，请先添加文件"))
            return

        from filecollector.gui_flet.ai_settings_dialog import load_ai_settings
        s = load_ai_settings()
        if (not s.get("enabled") or not s.get("base_url")
                or not s.get("api_key") or not s.get("model")):
            show_snack(self.page, _("请先在 AI 设置中配置 API"))
            return

        show_snack(self.page, _("正在让 AI 生成阅读指南..."))

        import threading

        def _do():
            try:
                from filecollector.ai_client import AIClient
                client = AIClient(
                    s["base_url"], s["api_key"], s["model"],
                    float(s.get("timeout", 60) or 60),
                )
                context = self._build_toc_prompt_context()
                prompt = self._build_toc_prompt(context)
                messages = [{"role": "user", "content": prompt}]
                data = client.chat(messages, None)
                content = (data.get("choices", [{}])[0]
                           .get("message", {}).get("content", ""))
                result = self._clean_ai_markdown(content)
            except Exception as ex:
                result = ""
                import logging
                logging.warning(f"TOC Gen failed: {ex}")

            self.page.run_task(self._on_toc_generated, result)

        threading.Thread(target=_do, daemon=True).start()

    async def _on_toc_generated(self, result: str) -> None:
        if not result:
            show_snack(self.page, _("AI 生成阅读指南失败"))
            return
        self._push_undo()
        from filecollector.models import ItemData
        self.engine.items.insert(0, ItemData("text", content=result))
        self.arrangement_panel.refresh()
        show_snack(self.page, _("AI 阅读指南已插入编排列表顶部"))

    def _build_toc_prompt_context(self) -> str:
        """构建阅读指南的上下文 (每个文件的前 15 行)."""
        import os
        lines = []
        for item in self.engine.items:
            if item.type == "file" and item.path:
                rel = item.path
                if self.engine.work_dir:
                    rel = display_path(item.path, work_dir=self.engine.work_dir)
                lines.append(f"### {rel}")
                try:
                    with open(item.path, "r", encoding="utf-8",
                              errors="replace") as f:
                        for i, line in enumerate(f):
                            if i >= 15:
                                break
                            lines.append(line.rstrip())
                except Exception:
                    lines.append("[无法读取文件内容]")
                lines.append("")
            elif item.type == "text":
                lines.append("### [自定义文本片段]")
                preview = (item.content or "")[:200]
                if len(item.content or "") > 200:
                    preview += "..."
                lines.append(preview)
                lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _build_toc_prompt(context: str) -> str:
        return (
            "你是一个高级软件架构师和文档专家。我将提供一个项目中的一系列文件路径及其开头部分的代码/内容摘要。\n"
            "请你根据这些信息，为这些文件生成一份结构化的 Markdown 格式的「阅读指南与目录」，并包含「文件关联性分析」。\n"
            "要求：\n"
            "1. 使用 Markdown 语法。\n"
            "2. 将文件按逻辑模块或功能进行分类。\n"
            "3. 为每个文件提供一句话的简要说明。\n"
            "4. 在「文件关联性分析」部分，简述这些文件是如何协同工作的。\n"
            "5. 直接输出 Markdown 内容，不要包含任何额外的解释。\n\n"
            "以下是文件列表及摘要：\n\n" + context
        )

    @staticmethod
    def _clean_ai_markdown(raw: str) -> str:
        s = raw.strip()
        if s.startswith("```markdown"):
            s = s[11:].strip()
        elif s.startswith("```"):
            s = s[3:].strip()
        if s.endswith("```"):
            s = s[:-3].strip()
        return s

    def _on_clear_cache(self, e):
        """清除工作区缓存 (确认 + 实际清理 + 通知)."""
        if not self.engine.work_dir:
            show_snack(self.page, _("尚未设置工作目录"))
            return

        def on_confirm(ev):
            self.page.pop_dialog()
            if ev.control.data == "yes":
                cleared = self.preprocess_runner.clear_workspace_cache()
                self.arrangement_panel.refresh()
                self.preview_panel.clear()
                msg = _("工作区缓存已清除")
                if cleared:
                    msg += f" ({cleared})"
                show_snack(self.page, msg)

        def on_cancel(ev):
            self.page.pop_dialog()

        dlg = ft.AlertDialog(
            title=ft.Text(_("确认清除缓存？")),
            content=ft.Text(_(
                "这将删除当前工作目录下的 .filecollector_cache 隐藏文件夹。\n"
                "下次处理相同文件时，将重新调用视觉语言大模型（VLM）并消耗 API Token。"
            )),
            actions=[
                secondary_btn(_("取消"), on_click=on_cancel),
                secondary_btn(
                    _("清除"), on_click=on_confirm, data="yes",
                ),
            ],
        )
        self.page.show_dialog(dlg)

    def _on_ai_settings_changed(self):
        """AI 设置 (含允许扩展名) 变更后, 重新评估编排列表中的二进制条目."""
        if not getattr(self, "preprocess_runner", None):
            return
        try:
            self.preprocess_runner.reevaluate_queue()
        except Exception:
            pass
        try:
            self.arrangement_panel.refresh()
        except Exception:
            pass

    def _on_shortcuts(self, e):
        """打开快捷键帮助"""
        dlg = ShortcutsDialog(self)
        self.page.show_dialog(dlg)

    def _on_about(self, e):
        """关于对话框"""
        dlg = ft.AlertDialog(
            title=ft.Text(_("关于 FileCollector")),
            content=ft.Column(
                [
                    ft.Text(_("文件收集与编排工具"), weight=ft.FontWeight.BOLD),
                    ft.Text(_("跨平台支持 Windows / macOS / Linux。")),
                    ft.Text(""),
                    ft.Text(_("主要功能："), weight=ft.FontWeight.BOLD),
                    ft.Text("• " + _("目录树浏览 + 多选勾选")),
                    ft.Text("• " + _("拖放排序 + 撤销 / 重做")),
                    ft.Text("• " + _("文字插入 + 常用语管理")),
                    ft.Text("• " + _("智能编码检测 (UTF-8 / GBK / 拉丁系)")),
                    ft.Text("• " + _("项目保存 / 加载 (.fcol)")),
                    ft.Text("• " + _("中英文切换 (跟随系统 / 中文 / English)")),
                    ft.Text("• " + _("完整键盘快捷键支持")),
                    ft.Text(""),
                    ft.Text(
                        _("开发者：Sam-Fic | License: MIT"),
                        color=ft.Colors.GREY_600,
                        size=12,
                    ),
                ],
                tight=True,
            ),
            actions=[
                secondary_btn(
                    _("关闭"), on_click=lambda _: self.page.pop_dialog()),
            ],
        )
        self.page.show_dialog(dlg)

    # ==================================================================
    # 辅助方法
    # ==================================================================

    def _update_toolbar_states(self):
        """同步顶部工具栏 (撤销/重做/Git 切换/全局搜索) 的可用状态"""
        if hasattr(self, "btn_undo"):
            self.btn_undo.disabled = not self.undo_manager.can_undo
            self.btn_redo.disabled = not self.undo_manager.can_redo
        # Git 切换 / 全局搜索需要工作目录 (git 是仓库操作, 全局搜索需指定根目录)
        has_work_dir = self.engine.work_dir is not None
        if hasattr(self, "btn_toggle_git"):
            self.btn_toggle_git.disabled = not has_work_dir
        if hasattr(self, "btn_global_search"):
            self.btn_global_search.disabled = not has_work_dir

    def _push_undo(self):
        """保存撤销状态 + 触发自动恢复保存 (5 秒防抖)."""
        self.undo_manager.push(self.engine.snapshot())
        self._schedule_auto_save()

    def _schedule_auto_save(self):
        """5 秒防抖自动保存 (避免频繁写盘)."""
        self._auto_save_debounced()

    @debounce(5.0)
    def _auto_save_debounced(self):
        self._save_recovery()

    def _save_recovery(self):
        """将当前会话状态写入恢复文件 (崩溃后可恢复)."""
        try:
            from filecollector.config import get_recovery_path, atomic_write_json
            import json
            state = self.engine.snapshot()
            state["_recovery_timestamp"] = time.time()
            atomic_write_json(get_recovery_path(), state)
        except Exception:
            pass

    def _clear_recovery(self):
        """删除恢复文件 (显式保存/加载/清空后调用)."""
        try:
            from filecollector.config import get_recovery_path
            import os
            path = get_recovery_path()
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _check_recovery_on_startup(self):
        """启动时检查是否存在未保存的恢复文件."""
        try:
            from filecollector.config import get_recovery_path
            import json
            import os
            path = get_recovery_path()
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
            items = state.get("items", [])
            if not items:
                os.remove(path)
                return

            def on_response(e):
                self.page.pop_dialog()
                if e.control.data == "restore":
                    try:
                        self.engine.restore(state)
                        self._refresh_all()
                        show_snack(self.page, _("已恢复未保存的会话"))
                    except Exception as ex:
                        show_snack(self.page, _("恢复失败: %s") % ex)
                else:
                    self._clear_recovery()

            dlg = ft.AlertDialog(
                title=ft.Text(_("发现未保存的会话")),
                content=ft.Text(
                    _("上次运行存在未保存的更改 (%d 个项目)。是否恢复？")
                    % len(items)),
                actions=[
                    secondary_btn(
                        _("丢弃"), on_click=on_response, data="discard"),
                    secondary_btn(
                        _("恢复"), on_click=on_response, data="restore"),
                ],
            )
            self.page.show_dialog(dlg)
        except Exception:
            pass

    def _revert_to_undo_token(self, token: int) -> None:
        """将撤销栈回退到指定 token 位置 (供 AI 撤回使用).

        逐次弹出 undo 栈直到栈大小 <= token, 每次恢复上一个快照.
        """
        self.undo_manager.set_in_progress(True)
        needs_refresh = False
        while self.undo_manager.can_undo and self.undo_manager.get_stack_size() > token:
            state = self.undo_manager.undo(self.engine.snapshot())
            if state is None:
                break
            self.engine.restore(state)
            needs_refresh = True
        self.undo_manager.set_in_progress(False)
        if needs_refresh:
            self._refresh_all()

    def _on_ai_batch_operation(self, summary: str) -> None:
        """AI 批量操作完成后, 显示带撤销按钮的 SnackBar."""
        if not self.undo_manager.can_undo:
            return

        def on_undo(e):
            snack.open = False
            self._on_undo(None)
            show_snack(self.page, _("已撤销 AI 的操作"))

        snack = ft.SnackBar(
            content=ft.Text(summary),
            action=_("撤销"),
            on_action=on_undo,
            duration=6000,
            persist=False,
        )
        self.page.overlay.append(snack)
        snack.open = True
        self.page.update()

    def _refresh_all(self):
        """刷新所有面板"""
        # 1. 重建目录树结构 (set_work_dir 内部会清空旧的 checked_paths)
        self.file_tree_panel.set_work_dir(self.engine.work_dir)
        # 2. 从 engine 恢复最新的勾选状态到文件树面板
        self.file_tree_panel.checked_paths = set(self.engine.checked_paths)
        # 3. 刷新各个面板的 UI 显示
        self.file_tree_panel.refresh()
        self.arrangement_panel.refresh()
        self.preview_panel.clear()
        self._update_subtitle()
        # 4. 同步工具栏 (撤销/重做) 状态
        self._update_toolbar_states()

    def _update_subtitle(self):
        """更新工作目录显示 + 同步与目录相关的菜单项可用状态"""
        has_work_dir = bool(self.engine.work_dir)
        if has_work_dir:
            self.work_dir_label.value = _("当前工作目录: %s") % self.engine.work_dir
        else:
            self.work_dir_label.value = _("当前工作目录: 未设置")
        # 工作目录未设置时, 把"保存项目/另存为/清除缓存"灰显
        if hasattr(self, "menu_save_project"):
            self.menu_save_project.disabled = not has_work_dir
            self.menu_save_project_as.disabled = not has_work_dir
            self.menu_clear_cache.disabled = not has_work_dir
        # 空状态引导 (普通空状态 / Git 空状态), 并彻底隐藏主界面
        self._refresh_empty_state()
        self.page.update()

    def _refresh_empty_state(self):
        """计算并显示正确的空状态, 同时隐藏主界面.

        对齐 GNOME 版 ab245ab 的 update_empty_state:
        - 未设置工作目录 -> 普通空状态 (folder-open)
        - Git 模式 + 有工作目录但无提交/非仓库 -> Git 空状态 (commit)
        - 其它情况 -> 显示主界面 (三栏布局)
        空状态下主界面不渲染/不可交互, 与 GNOME 版"替换 content"一致.
        """
        has_work_dir = bool(self.engine.work_dir)
        show_normal_empty = not has_work_dir
        show_git_empty = False
        if has_work_dir and getattr(self, "is_git_mode", False):
            show_git_empty = not self._git_data_available()
            if show_git_empty:
                self._configure_git_empty_page()

        if hasattr(self, "_empty_state_view"):
            self._empty_state_view.visible = show_normal_empty
        if hasattr(self, "_git_empty_state_view"):
            self._git_empty_state_view.visible = show_git_empty
        if hasattr(self, "_main_content"):
            self._main_content.visible = not (show_normal_empty or show_git_empty)
        # 工具栏按钮: 普通空状态(未设工作目录)时隐藏除三点菜单外的全部按钮,
        # 对齐 GNOME 版 ab245ab 的 update_empty_state (no_workdir 分支隐藏 btn_*)
        if show_normal_empty:
            if hasattr(self, "_toolbar_leading"):
                self._toolbar_leading.visible = False
            if hasattr(self, "_btn_ai_toggle"):
                self._btn_ai_toggle.visible = False
            # 空白状态不显示 "Working directory: not set" 标签
            if hasattr(self, "work_dir_label"):
                self.work_dir_label.visible = False
        else:
            if hasattr(self, "_toolbar_leading"):
                self._toolbar_leading.visible = True
            if hasattr(self, "_btn_ai_toggle"):
                self._btn_ai_toggle.visible = True
            if hasattr(self, "work_dir_label"):
                self.work_dir_label.visible = True

    def _git_data_available(self) -> bool:
        """Git 模式下是否有可显示的提交数据.

        参考 GNOME 版 git_data_available: 工作目录非空 + 是 Git 仓库
        + (已有提交 或 尚未加载完成) 才认为可用.
        """
        wd = self.engine.work_dir
        if not wd:
            return False
        if not is_git_repo(str(wd)):
            return False
        panel = getattr(self, "git_history_panel", None)
        if panel is None:
            return False
        if panel._commits:
            return True
        # 尚未加载完成时, 暂不显示空状态 (避免加载中闪烁)
        if not panel._all_loaded:
            return True
        return False

    def _configure_git_empty_page(self):
        """按当前仓库状态设置 Git 空状态的标题与描述.

        对齐 GNOME 版 configure_git_empty_page.
        """
        wd = self.engine.work_dir
        if wd and not is_git_repo(str(wd)):
            self._git_empty_title.value = _("未检测到 Git 仓库")
            self._git_empty_desc.value = _(
                "当前工作目录不是一个 Git 仓库，无法读取提交历史。"
                "请在该目录下执行 git init 进行初始化，或在包含版本库的工作目录中打开本应用。")
        else:
            self._git_empty_title.value = _("暂无提交记录")
            self._git_empty_desc.value = _(
                "当前 Git 仓库中还没有任何提交。完成首次 git commit 后，提交历史将显示在此处。")

    def show_preview(self, data: ItemData):
        """显示预览"""
        self.preview_panel.show_preview(data)
    def clear_preview(self):
        """清空预览"""
        self.preview_panel.clear()

    def open_file_location(self, path: str):
        """在文件管理器中显示文件."""
        import sys
        import subprocess
        import os
        try:
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
    # AI 集成: 状态快照 + 工具执行入口
    # ==================================================================
    # 这些方法供 ai_panel 调用, 把 LLM 决策映射到 engine mutation.
    # 复用 engine 的语义, 但省略了 GUI 特定的 tree 勾选步骤
    # (Flet file_tree_panel 自己管 checked_paths, 通过 _sync_to_engine
    # 推回 engine).

    def _ai_state_snapshot(self) -> tuple:
        """供 system prompt 使用: (work_dir, items, use_absolute, show_header)."""
        items: list[dict] = []
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
        return (work_dir, items,
                bool(self.engine.use_absolute),
                bool(self.engine.show_header))

    def _execute_ai_tool(self, name: str, arguments: dict) -> str:
        """AI 工具调用入口."""
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
            new_dir = Path(path).expanduser().resolve()
            if not new_dir.exists() or not new_dir.is_dir():
                return _("错误: 目录不存在: %s") % path
            self.engine.work_dir = new_dir
            self.engine.items.clear()
            self.engine.checked_paths.clear()
            self.file_tree_panel.set_work_dir(new_dir)
            self.arrangement_panel.refresh()
            self._update_subtitle()
            self._update_toolbar_states()
            return _("工作目录已切换到 %s") % new_dir

        if name == "add_files":
            paths = args.get("paths") or []
            if not isinstance(paths, list) or not paths:
                return _("错误: paths 必须是非空数组")
            self._push_undo()
            added: list[str] = []
            skipped: list[str] = []
            work_dir = self.engine.work_dir

            for p in paths:
                if not isinstance(p, str) or not p.strip():
                    skipped.append(str(p))
                    continue
                if not os.path.isfile(p):
                    skipped.append(p)
                    continue
                abs_path = str(Path(p).resolve())
                inside = False
                if work_dir is not None:
                    try:
                        inside = Path(abs_path).is_relative_to(work_dir)
                    except (ValueError, AttributeError):
                        inside = False
                if inside:
                    self.engine.add_file(abs_path, force_absolute=False)
                    self.file_tree_panel.checked_paths.add(abs_path)
                    added.append(abs_path)
                else:
                    self.engine.add_file(abs_path, force_absolute=True)
                    added.append(abs_path)

            # 推一次到 tree, 让勾选文件显示为已选
            self.file_tree_panel.refresh()
            self.arrangement_panel.refresh()
            # 触发新增 binary 条目的 VLM 预处理
            runner = getattr(self, "preprocess_runner", None)
            if runner:
                try:
                    runner.reevaluate_queue()
                except Exception:
                    pass
            total = len(added)
            # AI 批量操作通知
            summary = _("AI 添加了 %d 个文件") % total
            if skipped:
                summary += _("，跳过 %d 个") % len(skipped)
            self._on_ai_batch_operation(summary)
            if total and not skipped:
                return _("已添加 %d 个文件") % total
            if total and skipped:
                return _("已添加 %d 个文件 (跳过 %d 个无效路径)") % (
                    total, len(skipped))
            return _("已跳过所有 %d 个路径 (文件不存在)") % len(skipped)

        if name == "add_text":
            text = args.get("text") or ""
            position = args.get("position")
            if not isinstance(text, str):
                return _("错误: text 必须是字符串")
            self._push_undo()
            self.engine.add_text(text)
            new_index = len(self.engine.items) - 1
            try:
                target = int(position) if position is not None else new_index
            except (TypeError, ValueError):
                target = new_index
            target = max(0, min(target, len(self.engine.items) - 1))
            if target != new_index:
                self.engine.move_item(new_index, target)
                new_index = target
            self.arrangement_panel.refresh()
            self.arrangement_panel.selected_index = new_index
            self._on_ai_batch_operation(_("AI 插入了自定义文本"))
            return _("已插入文字")

        if name == "remove_item":
            try:
                idx = int(args.get("index"))
            except (TypeError, ValueError):
                return _("错误: index 必须是整数")
            if not (0 <= idx < len(self.engine.items)):
                return _("错误: index %d 超出范围 (0..%d)") % (
                    idx, len(self.engine.items) - 1)
            self._push_undo()
            data = self.engine.items[idx]
            if data.type == "file" and not data.force_absolute:
                self.engine.checked_paths.discard(data.path)
                self.file_tree_panel.checked_paths.discard(data.path)
            self.engine.remove_item(idx)
            self.arrangement_panel.refresh()
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
            self.engine.move_item(f, t)
            self.arrangement_panel.refresh()
            return _("已将 [%d] 移动到 [%d]") % (f, t)

        if name == "clear_items":
            self._push_undo()
            for p in list(self.engine.checked_paths):
                self.file_tree_panel.checked_paths.discard(p)
            self.engine.clear()
            self.arrangement_panel.refresh()
            self._on_ai_batch_operation(_("AI 清空了编排列表"))
            return _("已清空编排列表")

        if name == "set_use_absolute":
            value = bool(args.get("value"))
            self._push_undo()
            self.engine.use_absolute = value
            self.arrangement_panel.refresh()
            return _("路径模式: %s") % (
                _("使用绝对路径") if value else _("使用相对路径"))

        if name == "set_show_header":
            value = bool(args.get("value"))
            self._push_undo()
            self.engine.show_header = value
            self.arrangement_panel.refresh()
            return _("头部信息: %s") % (
                _("已开启") if value else _("已关闭"))

        if name == "list_files":
            return self._ai_list_files(args)

        if name == "read_file":
            return self._ai_read_file(args)

        if name == "list_items":
            return self._ai_list_items(args)

        if name == "get_git_status":
            return self._ai_get_git_status()

        if name == "get_git_diff":
            return self._ai_get_git_diff(args)

        if name == "get_git_log":
            return self._ai_get_git_log(args)

        if name == "get_git_commit_diff":
            return self._ai_get_git_commit_diff(args)

        if name == "add_git_diff":
            return self._ai_add_git_diff(args)

        if name == "add_git_commit_diff":
            return self._ai_add_git_commit_diff(args)

        if name == "add_git_diff_range":
            return self._ai_add_git_diff_range(args)

        if name == "add_file_snippet":
            return self._ai_add_file_snippet(args)

        return _("未知工具: %s") % name

    # ---------------------------------------------------------------- 文件扫描/读取
    # ==================================================================
    # VLM 预处理: 给 PreprocessRunner 用的钩子
    # ==================================================================

    _AI_BINARY_SNIFF_BYTES = 8192

    def _ai_skip_dirs(self) -> set[str]:
        """AI 文件扫描时生效的忽略目录 (内置 SKIP_DIRS + 用户偏好)."""
        from filecollector.gui_flet.constants import get_effective_skip_dirs
        return get_effective_skip_dirs()

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

        pattern_lower = pattern.lower() if pattern else None
        matches: list[tuple[str, int]] = []
        truncated = False
        root_str = str(root)
        for dirpath, dirnames, filenames in os.walk(root):
            if dirpath == root_str:
                rel_depth = 0
            else:
                rel_depth = dirpath[len(root_str):].count(os.sep)
            if rel_depth > max_depth:
                dirnames[:] = []
                continue
            dirnames[:] = [
                d for d in dirnames
                if d not in self._ai_skip_dirs() and not d.startswith(".")
            ]
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

        matches.sort(key=lambda x: x[0])
        shown = matches[:max_results]
        lines = [f"Found {len(matches)} file(s) under {root}"]
        if pattern:
            lines[0] += f" matching '{pattern}'"
        if truncated:
            lines[0] += f" (showing first {len(shown)})"
        lines.append("")
        for p, size in shown:
            rel = display_path(p, work_dir=root_str)
            lines.append(f"  {rel}  ({size} bytes)")
        return "\n".join(lines)

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

        if is_binary_file(path_str, self._AI_BINARY_SNIFF_BYTES):
            return _("错误: 文件看起来是二进制, 不支持读取: %s") % path_str

        try:
            size = path.stat().st_size
        except OSError:
            size = 0

        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for _i in range(start_line - 1):
                    f.readline()
                buf = f.read(max_bytes)
                # 若读到字节上限, 补全最后一行避免半行截断
                if len(buf) == max_bytes:
                    buf += f.readline()
                truncated_by_bytes = len(buf) > max_bytes
        except OSError as e:
            return _("错误: 读取失败: %s") % e

        lines = buf.splitlines()

        if len(lines) > max_lines:
            lines = lines[:max_lines]
            truncated_by_lines = True
        else:
            truncated_by_lines = False

        truncated = truncated_by_bytes or truncated_by_lines
        width = len(str(start_line + len(lines) - 1)
                    ) if lines else len(str(start_line))
        out: list[str] = [f"--- {path} (size: {size} bytes) ---"]
        for i, ln in enumerate(lines):
            out.append(f"{start_line + i:>{width}}  {ln}")
        if truncated:
            note = []
            if truncated_by_lines:
                note.append(_("更多行请用 start_line / max_lines 分段读取"))
            if truncated_by_bytes:
                note.append(_("内容被 max_bytes 截断"))
            out.append(f"… ({'; '.join(note)})")
        return "\n".join(out)

    def _ai_list_items(self, args: dict) -> str:
        kind_raw = (args.get("kind") or "").strip().lower()
        kind: Optional[str] = None
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

    # ---------------------------------------------------------------- Git AI 工具
    def _ai_get_git_status(self) -> str:
        if not self.engine.work_dir:
            return "Error: Work directory not set."
        try:
            from filecollector.git_service import get_status
            output = get_status(str(self.engine.work_dir))
            if not output.strip():
                return "Working tree is clean. No uncommitted changes."
            return output
        except Exception as e:
            return f"Error: {e}"

    def _ai_get_git_diff(self, args: dict) -> str:
        if not self.engine.work_dir:
            return "Error: Work directory not set."
        staged = bool(args.get("staged", False))
        try:
            from filecollector.git_service import (
                get_staged_diff, get_working_tree_diff)
            output = (
                get_staged_diff(str(self.engine.work_dir))
                if staged
                else get_working_tree_diff(str(self.engine.work_dir))
            )
            if not output.strip():
                return "No staged changes." if staged else "No unstaged changes."
            MAX_DIFF_BYTES = 81920
            if len(output) > MAX_DIFF_BYTES:
                return output[:MAX_DIFF_BYTES] + "\n\n... [Diff truncated due to size]"
            return output
        except Exception as e:
            return f"Error: {e}"

    def _ai_get_git_log(self, args: dict) -> str:
        if not self.engine.work_dir:
            return "Error: Work directory not set."
        try:
            max_count = int(args.get("max_count", 10))
        except (TypeError, ValueError):
            max_count = 10
        max_count = max(1, min(max_count, 50))
        try:
            from filecollector.git_service import get_log
            commits = get_log(str(self.engine.work_dir), max_count)
            if not commits:
                return "No commits found."
            lines = []
            for c in commits:
                lines.append(
                    f"{c.short_hash} | {c.author} | {c.date} | {c.message}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    def _ai_get_git_commit_diff(self, args: dict) -> str:
        if not self.engine.work_dir:
            return "Error: Work directory not set."
        commit_hash = (args.get("commit_hash") or "").strip()
        if not commit_hash or len(commit_hash) < 4 or len(commit_hash) > 64:
            return "Error: Invalid commit hash format."
        try:
            from filecollector.git_service import get_commit_diff
            output = get_commit_diff(str(self.engine.work_dir), commit_hash)
            MAX_DIFF_BYTES = 81920
            if len(output) > MAX_DIFF_BYTES:
                return output[:MAX_DIFF_BYTES] + "\n\n... [Commit Diff truncated]"
            return output
        except Exception as e:
            return f"Error: {e}"

    def _ai_add_git_diff(self, args: dict) -> str:
        """将 Git Diff 直接注入编排列表 (绕过 LLM 上下文)."""
        if not self.engine.work_dir:
            return "Error: Work directory not set."
        staged = bool(args.get("staged", False))
        try:
            from filecollector.git_service import get_diff
            diff = get_diff(str(self.engine.work_dir), staged=staged)
            if not diff.strip():
                return _("当前工作区没有未提交的改动。") if not staged \
                    else _("当前没有已暂存的改动。")
            mode = "staged" if staged else "working tree"
            md_text = f"# Git Diff ({mode})\n\n```diff\n{diff}\n```"
            self._push_undo()
            from filecollector.models import ItemData
            self.engine.items.append(ItemData("text", content=md_text))
            self.arrangement_panel.refresh()
            lines = len(diff.split("\n"))
            self._on_ai_batch_operation(
                _("已成功将 Git Diff 注入编排列表 (%d 行)") % lines)
            return _("已成功将 Git Diff 注入编排列表 (%d 行)。") % lines
        except Exception as e:
            return f"Error: {e}"

    def _ai_add_git_commit_diff(self, args: dict) -> str:
        """将指定 Commit 的 Diff 直接注入编排列表 (绕过 LLM)."""
        if not self.engine.work_dir:
            return "Error: Work directory not set."
        commit_hash = (args.get("commit_hash") or "").strip()
        if not commit_hash or len(commit_hash) < 4 or len(commit_hash) > 64:
            return "Error: Invalid commit hash format."
        try:
            from filecollector.git_service import get_commit_diff
            diff = get_commit_diff(str(self.engine.work_dir), commit_hash)
            if not diff.strip():
                return _("未找到该 Commit 的 Diff 或 Commit 不存在。")
            short = commit_hash[:7]
            md_text = f"# Git Commit: {short}\n\n```diff\n{diff}\n```"
            self._push_undo()
            from filecollector.models import ItemData
            self.engine.items.append(ItemData("text", content=md_text))
            self.arrangement_panel.refresh()
            lines = len(diff.split("\n"))
            self._on_ai_batch_operation(
                _("已成功将 Commit %s 的 Diff 注入编排列表 (%d 行)") % (short, lines))
            return _("已成功将 Commit %s 的 Diff 注入编排列表 (%d 行)。") % (short, lines)
        except Exception as e:
            return f"Error: {e}"

    def _ai_add_git_diff_range(self, args: dict) -> str:
        """将 Commit 范围的 Diff 直接注入编排列表 (绕过 LLM)."""
        if not self.engine.work_dir:
            return "Error: Work directory not set."
        from_hash = (args.get("from_hash") or "").strip()
        to_hash = (args.get("to_hash") or "HEAD").strip()
        if not from_hash or len(from_hash) < 4 or len(from_hash) > 64:
            return "Invalid from_hash."
        if len(to_hash) < 1 or len(to_hash) > 64:
            return "Invalid to_hash."
        try:
            from filecollector.git_service import run_git
            diff = run_git(str(self.engine.work_dir),
                           ["diff", f"{from_hash}..{to_hash}"])
            if not diff.strip():
                return _("从 %s 到 %s 没有代码差异。") % (from_hash[:7], to_hash[:7])
            log_output = run_git(str(self.engine.work_dir),
                                 ["log", "--oneline", f"{from_hash}..{to_hash}"])
            commit_count = sum(1 for l in log_output.split("\n") if l.strip())
            from_short = from_hash[:7]
            to_short = "HEAD" if to_hash == "HEAD" else to_hash[:7]
            md_text = f"# Git Diff: {from_short}..{to_short} ({commit_count} commits)\n\n```diff\n{diff}\n```"
            self._push_undo()
            from filecollector.models import ItemData
            self.engine.items.append(ItemData("text", content=md_text))
            self.arrangement_panel.refresh()
            lines = len(diff.split("\n"))
            self._on_ai_batch_operation(
                _("已成功将 %s..%s 的 Diff 注入编排列表 (%d commits, %d 行)")
                % (from_short, to_short, commit_count, lines))
            return _("已成功将 %s..%s 的 Diff 注入编排列表 (%d commits, %d 行)。") % (
                from_short, to_short, commit_count, lines)
        except Exception as e:
            return f"Error: {e}"

    def _ai_add_file_snippet(self, args: dict) -> str:
        """将文件指定行范围 (片段) 加入编排列表 (绕过 LLM 上下文)."""
        path = (args.get("path") or "").strip()
        try:
            sl = int(args.get("start_line") or 0)
            el = int(args.get("end_line") or 0)
        except (TypeError, ValueError):
            return "Error: start_line / end_line must be integers."
        if not path or sl <= 0 or el < sl:
            return "Error: Invalid parameters (path required, start_line>0, end_line>=start_line)."
        work_dir = self.engine.work_dir
        if work_dir is None:
            return "Error: Work directory not set."
        p = Path(path)
        if not p.is_absolute():
            p = Path(work_dir) / path
        p = p.expanduser().resolve()
        try:
            inside = p.is_relative_to(Path(work_dir))
        except (ValueError, AttributeError):
            inside = False
        if not inside:
            return "Error: Path is outside the work directory."
        if not p.is_file():
            return "Error: File does not exist: %s" % p
        # 普通文本片段无需 VLM 预处理, 但 binary 片段仍走转换流程
        self._push_undo()
        self.engine.add_file_snippet(str(p), sl, el, force_absolute=False)
        self.file_tree_panel.checked_paths.add(str(p))
        self.file_tree_panel.refresh()
        self.arrangement_panel.refresh()
        runner = getattr(self, "preprocess_runner", None)
        if runner:
            try:
                runner.reevaluate_queue()
            except Exception:
                pass
        name = p.name
        self._on_ai_batch_operation(_("已添加片段: %s [L%d-L%d]") % (name, sl, el))
        return _("已添加片段: %s [L%d-L%d]") % (name, sl, el)

    # ==================================================================
    # VLM 预处理: 给 PreprocessRunner 用的钩子
    # ==================================================================
    def _get_work_dir_for_preprocess(self) -> Optional[str]:
        wd = self.engine.work_dir
        return str(wd) if wd else None

    def _get_allowed_binary_exts(self) -> list[str]:
        """返回当前允许被 VLM 转换的扩展名列表 (实时读取 settings)."""
        try:
            return list(get_allowed_binary_extensions())
        except Exception:
            return []

    # ==================================================================
    # 文件树 "选择行": 解析行范围并将片段加入编排列表
    # ==================================================================
    def add_line_ranges_to_queue(self, path_str: str, input_text: str) -> None:
        """解析行范围 (1-10,15,20-25) 并将每个范围作为片段加入编排列表."""
        parts = input_text.split(",")
        starts: list[int] = []
        ends: list[int] = []
        for part in parts:
            trimmed = part.strip()
            if not trimmed:
                continue
            if "-" in trimmed:
                bounds = trimmed.split("-", 1)
                try:
                    s = int(bounds[0].strip())
                    e = int(bounds[1].strip())
                except ValueError:
                    show_snack(self.page, _("无效的行范围: %s") % trimmed)
                    return
                if s > 0 and e > 0 and s <= e:
                    starts.append(s)
                    ends.append(e)
                else:
                    show_snack(self.page, _("无效的行范围: %s") % trimmed)
                    return
            else:
                try:
                    line = int(trimmed)
                except ValueError:
                    show_snack(self.page, _("无效的行号: %s") % trimmed)
                    return
                if line > 0:
                    starts.append(line)
                    ends.append(line)
                else:
                    show_snack(self.page, _("无效的行号: %s") % trimmed)
                    return

        if not starts:
            show_snack(self.page, _("未输入有效的行范围"))
            return

        abs_path = str(Path(path_str).resolve())
        self._push_undo()
        for s, e in zip(starts, ends):
            self.engine.add_file_snippet(abs_path, s, e, force_absolute=False)
        self.file_tree_panel.checked_paths.add(abs_path)
        self.file_tree_panel.refresh()
        self.arrangement_panel.refresh()

    def _on_preprocess_status(self, item: ItemData) -> None:
        """状态变化 (来自后台线程). 刷新列表与预览 (若预览的就是该条目)."""
        try:
            self.arrangement_panel.notify_preprocess_status_changed(item)
        except Exception:
            pass
        # 同步刷新预览面板: 状态变化 (如 CHECKING -> PROCESSING) 时,
        # 预览区的提示语必须与列表徽标保持一致, 否则用户会看到错位的状态.
        try:
            sel = getattr(self.arrangement_panel, "selected_index", -1)
            items = self.engine.items
            if 0 <= sel < len(items) and items[sel] is item:
                self.show_preview(item)
        except Exception:
            pass

    def _on_preprocess_preview(self, item: ItemData) -> None:
        """预处理结果 (来自后台线程). 若当前正显示该条目, 立即更新预览."""
        try:
            sel = getattr(self.arrangement_panel, "selected_index", -1)
            items = self.engine.items
            if 0 <= sel < len(items) and items[sel] is item:
                self.show_preview(item)
        except Exception:
            pass

    # ==================================================================
    # VLM 预处理队列: 进度卡片 + 暂停/取消
    # ==================================================================
    def _build_vlm_progress_card(self) -> ft.Container:
        """构建悬浮在右下角的 VLM 预处理进度卡片."""
        self._vlm_status_label = ft.Text(
            _("正在预处理 0/0 个文件..."),
            size=13,
            weight=ft.FontWeight.W_600,
            expand=True,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self._vlm_pause_btn = icon_btn(
            icon=ft.Icons.PAUSE,
            tooltip=_("暂停"),
            on_click=self._on_vlm_pause_toggle,
        )
        self._vlm_cancel_btn = icon_btn(
            icon=ft.Icons.STOP,
            tooltip=_("取消全部"),
            on_click=self._on_vlm_cancel,
        )
        self._vlm_progress_bar = ft.ProgressBar(
            value=0,
            height=4,
        )

        card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self._vlm_status_label,
                            self._vlm_pause_btn,
                            self._vlm_cancel_btn,
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._vlm_progress_bar,
                ],
                spacing=6,
                tight=True,
            ),
            width=280,
            padding=ft.Padding(left=12, top=10, right=12, bottom=10),
            border_radius=12,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            right=16,
            bottom=16,
            visible=False,
        )
        return card

    def _on_vlm_progress_changed(self, completed: int, total: int, active: int):
        """队列进度回调 (可能来自 UI 线程或 worker 线程).

        直接更新控件, 不用 page.run_task — run_task 在 UI 线程同步代码中
        调用会死锁 (等 Flutter 响应, 但事件循环被当前 handler 占住).
        control.update() 本身线程安全.
        """
        try:
            self._vlm_status_label.value = _(
                "正在预处理 %d/%d 个文件...") % (completed, total)
            self._vlm_progress_bar.value = (
                completed / total) if total > 0 else 0
            self._vlm_progress_card.update()
        except Exception:
            pass

    def _on_vlm_state_changed(self, has_tasks: bool):
        """队列状态回调: 控制进度卡片可见性."""
        try:
            self._vlm_progress_card.visible = has_tasks
            self._vlm_progress_card.update()
        except Exception:
            pass

    def _on_vlm_pause_toggle(self, e):
        if self.vlm_queue.is_paused:
            self.vlm_queue.resume()
            self._vlm_pause_btn.icon = ft.Icons.PAUSE
            self._vlm_pause_btn.tooltip = _("暂停")
        else:
            self.vlm_queue.pause()
            self._vlm_pause_btn.icon = ft.Icons.PLAY_ARROW
            self._vlm_pause_btn.tooltip = _("继续")
        try:
            self._vlm_pause_btn.update()
        except Exception:
            pass

    def _on_vlm_cancel(self, e):
        self.vlm_queue.cancel()
        # cancel() 同时清掉了 _is_paused, 把暂停按钮图标复位为 PAUSE
        self._vlm_pause_btn.icon = ft.Icons.PAUSE
        self._vlm_pause_btn.tooltip = _("暂停")
        try:
            self._vlm_pause_btn.update()
        except Exception:
            pass
