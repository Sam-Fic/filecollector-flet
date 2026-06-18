"""Flet 版本主视图 - 三栏布局"""

from __future__ import annotations

import fnmatch
import os
import threading
from pathlib import Path
from typing import Optional

import flet as ft

from filecollector.engine import FileCollectorEngine
from filecollector.models import ItemData
from filecollector.utils import safe_read_file
from filecollector.i18n import _, add_listener, remove_listener
from filecollector.config import load_settings, save_settings
from filecollector.gui_flet.file_tree import FileTreePanel
from filecollector.gui_flet.arrangement_list import ArrangementListPanel
from filecollector.gui_flet.preview_panel import PreviewPanel
from filecollector.gui_flet.ai_panel import AIPanel
from filecollector.gui_flet.ai_settings_dialog import (
    load_ai_settings, AISettingsDialog,
)
from filecollector.gui_flet.dialogs import (
    SettingsDialog, PhrasesDialog, ShortcutsDialog, TextEditDialog
)
from filecollector.gui_flet.snack import show_snack
from filecollector.gui_flet.undo import UndoManager


class MainView:
    """主视图容器 - 三栏卡片式布局"""

    def __init__(self, page: ft.Page):
        self.page = page
        self.engine = FileCollectorEngine()
        self.undo_manager = UndoManager()
        self.common_phrases: list[str] = []

        # 共享文件选择器（避免每次创建新实例导致超时）
        self._file_picker = ft.FilePicker()
        self.page.services.append(self._file_picker)
        self.page.update()

        # 加载常用语
        if hasattr(self.engine, "load_common_phrases_from_disk"):
            self.engine.load_common_phrases_from_disk()
            self.common_phrases = list(self.engine.common_phrases)

        # 构建 UI
        self._build_ui()

        # 语言切换监听
        add_listener(self._on_language_changed)

        # 键盘快捷键
        self.page.on_keyboard_event = self._on_keyboard

        # 窗口最小宽度强制（Linux/GTK 上 min_width 不一定生效）
        self._min_width = 1100
        self.page.on_resize = self._on_resize

    def _on_keyboard(self, e: ft.KeyboardEvent):
        """处理键盘快捷键"""
        key = e.key
        ctrl = e.ctrl
        shift = e.shift

        if ctrl and key == "Z" and not shift:
            self._on_undo(None)
        elif ctrl and key == "Z" and shift:
            self._on_redo(None)
        elif ctrl and key == "O":
            self._on_load_project(None)
        elif ctrl and key == "S" and not shift:
            self._on_save_project(None)
        elif ctrl and key == "S" and shift:
            self._on_save_project_as(None)
        elif ctrl and key == "E":
            self.arrangement_panel._on_add_external(None)
        elif ctrl and key == "I" and not shift:
            self.arrangement_panel._on_insert_text_above(None)
        elif ctrl and key == "I" and shift:
            self.arrangement_panel._on_insert_text_below(None)
        elif ctrl and key == "N":
            self.arrangement_panel._on_clear(None)
        elif ctrl and key == "G":
            self.arrangement_panel._on_generate_txt(None)
        elif ctrl and key == "C" and shift:
            self.arrangement_panel._on_generate_clipboard(None)
        elif ctrl and key == ",":
            self._on_settings(None)
        elif ctrl and key == "/":
            self._on_shortcuts(None)
        elif key == "F1":
            self._on_about(None)
        elif ctrl and key == "Q":
            self._on_quit(None)

    def _build_ui(self):
        """构建三栏布局"""
        # 左侧文件树面板
        self.file_tree_panel = FileTreePanel(self)

        # 中间编排列表面板
        self.arrangement_panel = ArrangementListPanel(self)

        # 右侧预览面板
        self.preview_panel = PreviewPanel(self)

        # AI 面板（默认隐藏）
        self.ai_panel = AIPanel(self)

        # 三栏分割器
        self.main_row = ft.Row(
            [
                self.file_tree_panel.container,
                self.arrangement_panel.container,
                self.preview_panel.container,
            ],
            spacing=8,
            expand=True,
        )

        # 主容器
        self.container = ft.Container(
            content=ft.Column(
                [
                    self._build_app_bar(),
                    ft.Container(
                        content=self.main_row,
                        expand=True,
                        padding=ft.Padding(left=8, right=8, top=0, bottom=0),
                    ),
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
        )

    def _build_app_bar(self) -> ft.Control:
        """构建顶部应用栏 (使用 Container 替代 AppBar, 避免 Material 3 滚动阴影)"""
        # 左侧操作
        leading = ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.UNDO,
                    tooltip=_("撤销") + " (Ctrl+Z)",
                    on_click=self._on_undo,
                ),
                ft.IconButton(
                    icon=ft.Icons.REDO,
                    tooltip=_("重做") + " (Ctrl+Shift+Z)",
                    on_click=self._on_redo,
                ),
                ft.VerticalDivider(),
                ft.ElevatedButton(
                    _("打开文件夹"),
                    icon=ft.Icons.FOLDER_OPEN,
                    on_click=self._on_open_folder,
                ),
            ],
            spacing=0,
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
        actions = ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.SMART_TOY,
                    tooltip=_("AI 助手"),
                    on_click=self._on_toggle_ai,
                    padding=0,
                ),
                ft.PopupMenuButton(
                    icon=ft.Icons.MORE_VERT,
                    padding=0,
                    items=[
                        ft.PopupMenuItem(
                            content=ft.Text(_("保存项目")),
                            icon=ft.Icons.SAVE,
                            on_click=self._on_save_project,
                        ),
                        ft.PopupMenuItem(
                            content=ft.Text(_("项目另存为...")),
                            icon=ft.Icons.SAVE_AS,
                            on_click=self._on_save_project_as,
                        ),
                        ft.PopupMenuItem(
                            content=ft.Text(_("打开项目")),
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=self._on_load_project,
                        ),
                        ft.PopupMenuItem(),  # 分隔符
                        ft.PopupMenuItem(
                            content=ft.Text(_("语言设置")),
                            icon=ft.Icons.LANGUAGE,
                            on_click=self._on_settings,
                        ),
                        ft.PopupMenuItem(
                            content=ft.Text(_("AI 助手设置")),
                            icon=ft.Icons.SMART_TOY,
                            on_click=self._on_ai_settings,
                        ),
                        ft.PopupMenuItem(
                            content=ft.Text(_("常用语管理")),
                            icon=ft.Icons.CHAT,
                            on_click=self._on_phrases,
                        ),
                        ft.PopupMenuItem(),
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
                        ft.PopupMenuItem(),
                        ft.PopupMenuItem(
                            content=ft.Text(_("退出")),
                            icon=ft.Icons.CLOSE,
                            on_click=self._on_quit,
                        ),
                    ],
                ),
            ],
            spacing=0,
        )

        return ft.Container(
            content=ft.Stack(
                [
                    ft.Container(
                        content=title,
                        alignment=ft.Alignment(0, 0),
                        expand=True,
                    ),
                    ft.Row(
                        [
                            ft.Container(content=leading, width=220),
                            ft.Container(expand=True),
                        ],
                        spacing=0,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(
                        content=actions,
                        right=0,
                        top=0,
                        bottom=0,
                    ),
                ],
                expand=True,
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
                self.file_tree_panel.set_work_dir(self.engine.work_dir)
                self._update_subtitle()
                self.arrangement_panel.refresh()
                show_snack(self.page, _("已设置工作目录: %s") % self.engine.work_dir)

        self.page.run_task(pick)

    def _on_resize(self, e):
        """强制窗口最小宽度"""
        if self.page.window.width < self._min_width:
            self.page.window.width = self._min_width
            self.page.update()
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

    def _on_save_project(self, e):
        """保存项目 (若有已保存路径则直接覆盖, 否则另存为)."""
        if getattr(self.engine, "project_file", None):
            try:
                self.engine.common_phrases = list(self.common_phrases)
                self.engine.save_project(self.engine.project_file)
                show_snack(self.page, _("项目已保存: %s") %
                           self.engine.project_file)
            except Exception as ex:
                show_snack(self.page, _("保存失败: %s") % ex)
            return
        self._on_save_project_as(e)

    def _on_load_project(self, e):
        """加载项目"""

        async def pick():
            files = await self._file_picker.pick_files(
                dialog_title=_("打开项目"),
                allowed_extensions=["project.json", "fcol", "fcol.json"],
            )
            if files:
                try:
                    self.engine.load_project(files[0].path)
                    self._refresh_all()
                    self.common_phrases = list(self.engine.common_phrases)
                    show_snack(self.page, _("项目已加载: %s") % files[0].path)
                except Exception as ex:
                    show_snack(self.page, _("加载失败: %s") % ex)

        self.page.run_task(pick)

    def _on_settings(self, e):
        """打开设置"""
        dlg = SettingsDialog(self)
        self.page.show_dialog(dlg)

    def _on_ai_settings(self, e):
        """打开 AI 设置"""
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
                except Exception as ex:
                    show_snack(self.page, _("保存失败: %s") % ex)

        self.page.run_task(pick)

    def _on_quit(self, e):
        """退出应用 (列表非空时确认, 对齐 Qt 版 closeEvent)."""
        if self.engine.items:
            def on_confirm(e):
                if e.control.data == "yes":
                    self.page.pop_dialog()
                    self.page.window.close()
                else:
                    self.page.pop_dialog()

            dlg = ft.AlertDialog(
                title=ft.Text(_("确认退出")),
                content=ft.Text(_("编排列表不为空，确定退出吗？")),
                actions=[
                    ft.TextButton(_("取消"), on_click=on_confirm, data="no"),
                    ft.TextButton(_("确定"), on_click=on_confirm, data="yes"),
                ],
            )
            self.page.show_dialog(dlg)
        else:
            self.page.window.close()

    def _on_phrases(self, e):
        """打开常用语管理"""
        dlg = PhrasesDialog(self)
        self.page.show_dialog(dlg)

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
                ft.TextButton(
                    _("关闭"), on_click=lambda _: self.page.pop_dialog()),
            ],
        )
        self.page.show_dialog(dlg)

    # ==================================================================
    # 辅助方法
    # ==================================================================

    def _push_undo(self):
        """保存撤销状态"""
        self.undo_manager.push(self.engine.snapshot())

    def _refresh_all(self):
        """刷新所有面板"""
        self.file_tree_panel.refresh()
        self.arrangement_panel.refresh()
        self.preview_panel.clear()
        self._update_subtitle()

    def _update_subtitle(self):
        """更新工作目录显示"""
        if self.engine.work_dir:
            self.work_dir_label.value = _("当前工作目录: %s") % self.engine.work_dir
        else:
            self.work_dir_label.value = _("当前工作目录: 未设置")
        self.page.update()

    def show_preview(self, data: ItemData):
        """显示预览"""
        self.preview_panel.show_preview(data)

    def clear_preview(self):
        """清空预览"""
        self.preview_panel.clear()

    def open_file_location(self, path: str):
        """在文件管理器中显示文件 (对齐 Qt 版 _open_file_location)."""
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
    # 跟 PySide6 走相同的语义, 但省略了 GUI 特定的 tree 勾选步骤
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
        """AI 工具调用入口, 复刻 PySide6 的同名方法."""
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
            total = len(added)
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
            return _("已清空编排列表")

        if name == "set_use_absolute":
            value = bool(args.get("value"))
            self._push_undo()
            self.engine.use_absolute = value
            self.arrangement_panel.refresh()
            return _("路径模式: %s") % (
                _("绝对路径") if value else _("相对路径"))

        if name == "set_show_header":
            value = bool(args.get("value"))
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

        return _("未知工具: %s") % name

    # ---------------------------------------------------------------- 文件扫描/读取
    _AI_SKIP_DIRS = {
        ".git", ".hg", ".svn", ".idea", ".vscode", ".venv", "venv", "env",
        "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache",
        "dist", "build", ".next", ".nuxt", "target", ".gradle",
    }
    _AI_BINARY_SNIFF_BYTES = 8192

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
                rel_depth = dirpath[len(root_str):].count(os.sep) + 1
            if rel_depth > max_depth:
                dirnames[:] = []
                continue
            dirnames[:] = [
                d for d in dirnames
                if d not in self._AI_SKIP_DIRS and not d.startswith(".")
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
            try:
                rel = os.path.relpath(p, root_str)
            except ValueError:
                rel = p
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

        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for _i in range(start_line - 1):
                    f.readline()
                buf = f.read(max_bytes + 4096)
        except OSError as e:
            return _("错误: 读取失败: %s") % e

        lines = buf.splitlines()
        truncated_by_bytes = False
        if len(buf) > max_bytes:
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
