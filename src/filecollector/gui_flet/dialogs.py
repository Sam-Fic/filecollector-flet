"""对话框组件"""

from __future__ import annotations

import time
from typing import Optional

import flet as ft

from filecollector.i18n import _
from filecollector.config import load_settings, save_settings, get_common_phrases_path
from filecollector.gui_flet.ai_settings_dialog import AISettingsDialog
from filecollector.gui_flet.snack import show_snack


class SettingsDialog(ft.AlertDialog):
    """语言设置对话框"""

    def __init__(self, main_view):
        self.main_view = main_view
        self.radio_group = ft.RadioGroup(
            content=ft.Column(
                [
                    ft.Radio(value="", label=_("跟随系统")),
                    ft.Radio(value="zh_CN", label="中文"),
                    ft.Radio(value="en", label="English"),
                ]
            ),
            value=self._get_current_language(),
            on_change=self._on_language_change,
        )
        super().__init__(
            title=ft.Text(_("设置界面语言")),
            content=ft.Column(
                [
                    ft.Text(_("选择后立即生效。"), color=ft.Colors.GREY_600),
                    ft.Divider(),
                    self.radio_group,
                ],
                tight=True,
            ),
            actions=[
                ft.TextButton(_("取消"), on_click=self._on_cancel),
                ft.TextButton(_("确定"), on_click=self._on_accept),
            ],
        )

    def _get_current_language(self) -> str:
        settings = load_settings()
        return settings.get("language", "")

    def _on_language_change(self, e):
        # 实时更新语言
        pass

    def _on_accept(self, e):
        lang = self.radio_group.value
        settings = load_settings()
        settings["language"] = lang
        save_settings(settings)

        # 应用新语言
        from filecollector.i18n import set_language
        set_language(lang, notify=True)

        self.main_view.page.pop_dialog()

        # 弹出确认重启对话框
        def on_confirm_restart(ev):
            self.main_view.page.pop_dialog()
            if ev.control.data == "yes":
                self._restart_application()

        confirm_dlg = ft.AlertDialog(
            title=ft.Text(_("提示")),
            content=ft.Text(_("语言设置已保存，重启应用后生效。是否现在重启？")),
            actions=[
                ft.TextButton(_("稍后"), on_click=on_confirm_restart, data="no"),
                ft.TextButton(_("立即重启"), on_click=on_confirm_restart, data="yes"),
            ],
        )
        self.main_view.page.show_dialog(confirm_dlg)

    def _restart_application(self):
        """重启应用程序 (强制终止旧进程以释放 IPC 端口与单实例锁)."""
        import sys
        import subprocess
        import os
        import signal

        is_frozen = getattr(sys, 'frozen', False)

        if is_frozen:
            cmd = [sys.executable] + sys.argv[1:]
        else:
            if sys.argv and sys.argv[0].endswith(".py"):
                cmd = [sys.executable, sys.argv[0], "--flet"] + sys.argv[1:]
            else:
                cmd = [sys.executable, "-m", "filecollector", "--flet"] + sys.argv[1:]

        try:
            if sys.platform == "win32":
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                DETACHED_PROCESS = 0x00000008
                subprocess.Popen(cmd, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
            else:
                subprocess.Popen(cmd, start_new_session=True)
        except Exception:
            pass

        # 杀死整个进程组 (包含 Flutter 引擎子进程), 避免窗口残留
        # 新进程已由 start_new_session 隔离, 不受影响
        if sys.platform != "win32":
            os.killpg(os.getpgid(0), signal.SIGKILL)
        else:
            os._exit(0)

    def _on_cancel(self, e):
        self.main_view.page.pop_dialog()


class PhrasesDialog(ft.AlertDialog):
    """常用语选择 / 管理对话框.

    - 选择模式 (select_mode=True): 单击选中, 双击条目即返回该条目
      (用于 TextEditDialog 的"常用语"按钮).
    - 管理模式 (select_mode=False): 提供 新增 / 编辑 / 删除 / 关闭 操作,
      双击条目触发编辑.
    """

    def __init__(self, main_view, select_mode: bool = False,
                 on_phrase_selected=None):
        self.main_view = main_view
        self._select_mode = bool(select_mode)
        self.phrases = list(main_view.common_phrases)
        self.selected_index: int = -1
        # 双击检测
        self._last_click_idx: int = -1
        self._last_click_ts: float = 0.0
        # 选择模式回调: 选中短语后通知调用方
        self._on_phrase_selected_cb = on_phrase_selected

        self.list_view = ft.ListView(
            expand=True,
            spacing=2,
        )

        # 管理模式按钮
        self.btn_edit = ft.ElevatedButton(
            _("编辑"),
            icon=ft.Icons.EDIT,
            on_click=self._on_edit,
            disabled=True,
        )
        self.btn_delete = ft.ElevatedButton(
            _("删除"),
            icon=ft.Icons.DELETE,
            color=ft.Colors.WHITE,
            bgcolor=ft.Colors.RED_600,
            on_click=self._on_delete,
            disabled=True,
        )

        # 选择模式按钮行
        if self._select_mode:
            actions_row = ft.Row(
                [
                    ft.ElevatedButton(
                        _("添加"),
                        icon=ft.Icons.ADD,
                        on_click=self._on_add,
                    ),
                    ft.Container(expand=True),
                    ft.TextButton(_("取消"), on_click=self._on_cancel),
                    ft.ElevatedButton(
                        _("确定"),
                        icon=ft.Icons.CHECK,
                        on_click=self._on_accept,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )
            close_action = None
        else:
            actions_row = ft.Row(
                [
                    ft.ElevatedButton(
                        _("添加"),
                        icon=ft.Icons.ADD,
                        on_click=self._on_add,
                    ),
                    self.btn_edit,
                    self.btn_delete,
                ],
                alignment=ft.MainAxisAlignment.START,
            )
            close_action = ft.TextButton(_("关闭"), on_click=self._on_close)

        super().__init__(
            title=ft.Text(
                _("插入常用语") if self._select_mode else _("常用语管理")),
            content=ft.Column(
                [
                    ft.Container(
                        content=self.list_view,
                        height=240,
                        padding=ft.Padding(left=4, top=4, right=4, bottom=4),
                    ),
                    actions_row,
                ],
                tight=True,
            ),
            actions=[close_action] if close_action else [],
        )

        self._refresh_list()

    def _refresh_list(self):
        self.list_view.controls.clear()
        if not self.phrases:
            self.list_view.controls.append(
                ft.Container(
                    content=ft.Text(_("暂无常用语"), color=ft.Colors.GREY_600),
                    padding=12,
                    alignment=ft.alignment.Alignment(0, 0),
                )
            )
            self._set_actions_enabled(False)
        else:
            for idx, phrase in enumerate(self.phrases):
                is_selected = idx == self.selected_index
                display = phrase if len(phrase) <= 60 else phrase[:60] + "..."
                self.list_view.controls.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(display, size=14, expand=True,
                                        no_wrap=True, tooltip=phrase,
                                        color=ft.Colors.WHITE if is_selected else None),
                            ],
                        ),
                        padding=ft.Padding(left=10, top=8, right=10, bottom=8),
                        border_radius=6,
                        bgcolor=ft.Colors.BLUE_600 if is_selected
                        else ft.Colors.SURFACE_CONTAINER_LOW,
                        on_click=lambda e, i=idx: self._on_item_click(i),
                        ink=True,
                    )
                )
            self._set_actions_enabled(self.selected_index >= 0)
        self.main_view.page.update()

    def _set_actions_enabled(self, enabled: bool):
        """启用/禁用编辑和删除按钮 (仅管理模式)."""
        if not self._select_mode:
            self.btn_edit.disabled = not enabled
            self.btn_delete.disabled = not enabled

    def _on_item_click(self, idx: int):
        """条目点击: 检测双击 (同一条目 300ms 内两次点击)."""
        now = time.monotonic()
        if (idx == self._last_click_idx
                and now - self._last_click_ts < 0.3):
            # 双击
            self._last_click_idx = -1
            self._last_click_ts = 0.0
            self._on_double_click(idx)
            return
        # 单击
        self._last_click_idx = idx
        self._last_click_ts = now
        self._on_select(idx)

    def _on_select(self, idx: int):
        """单击选中条目."""
        self.selected_index = idx
        self._refresh_list()

    def _on_double_click(self, idx: int):
        """双击条目: 选择模式 -> 确定; 管理模式 -> 编辑."""
        self.selected_index = idx
        self._refresh_list()
        if self._select_mode:
            self._on_accept(None)
        else:
            self._on_edit(None)

    def _on_add(self, e):
        """新增常用语."""
        self._open_edit_dialog(_("新增常用语"), "")

    def _on_edit(self, e):
        """编辑选中常用语."""
        if not (0 <= self.selected_index < len(self.phrases)):
            return
        current = self.phrases[self.selected_index]
        self._open_edit_dialog(_("编辑常用语"), current)

    def _open_edit_dialog(self, title: str, default: str):
        """打开编辑对话框 (新增/编辑共用)."""
        text_field = ft.TextField(
            value=default,
            multiline=True,
            min_lines=2,
            max_lines=6,
            label=title,
            autofocus=True,
        )

        def on_submit(e):
            text = (text_field.value or "").strip()
            if not text:
                self.main_view.page.pop_dialog()
                return
            if title == _("新增常用语"):
                self.phrases.append(text)
                self.selected_index = len(self.phrases) - 1
            else:
                # 编辑模式: 替换当前选中项
                if 0 <= self.selected_index < len(self.phrases):
                    self.phrases[self.selected_index] = text
            self._persist()
            self._refresh_list()
            self.main_view.page.pop_dialog()

        dlg = ft.AlertDialog(
            title=ft.Text(title),
            content=text_field,
            actions=[
                ft.TextButton(
                    _("取消"),
                    on_click=lambda _: self.main_view.page.pop_dialog()),
                ft.TextButton(_("确定"), on_click=on_submit),
            ],
        )
        self.main_view.page.show_dialog(dlg)

    def _on_delete(self, e):
        """删除选中常用语 (带确认, 使用文本匹配避免 stale index)."""
        if not (0 <= self.selected_index < len(self.phrases)):
            return
        phrase_to_delete = self.phrases[self.selected_index]

        def on_confirm(e):
            self.main_view.page.pop_dialog()
            try:
                self.phrases.remove(phrase_to_delete)
            except ValueError:
                return
            self.selected_index = min(
                self.selected_index, max(len(self.phrases) - 1, 0))
            self._persist()
            self._refresh_list()

        def on_cancel(e):
            self.main_view.page.pop_dialog()  # 关闭确认对话框

        confirm_dlg = ft.AlertDialog(
            title=ft.Text(_("确认")),
            content=ft.Text(_("删除选中常用语？")),
            actions=[
                ft.TextButton(_("取消"), on_click=on_cancel),
                ft.TextButton(_("确定"), on_click=on_confirm),
            ],
        )
        self.main_view.page.show_dialog(confirm_dlg)

    def _on_accept(self, e):
        """确定: 选择模式返回选中条目并关闭本弹窗."""
        if self._select_mode:
            phrase = None
            if 0 <= self.selected_index < len(self.phrases):
                phrase = self.phrases[self.selected_index]
            # 先通知调用方回填, 再关闭常用语弹窗 (调用方保留自定义文字弹窗)
            if self._on_phrase_selected_cb:
                self._on_phrase_selected_cb(phrase)
        self.main_view.page.pop_dialog()

    def _on_cancel(self, e):
        """取消 (选择模式)."""
        self.main_view.page.pop_dialog()

    def _on_close(self, e):
        """关闭 (管理模式): 同步常用语到主视图和引擎."""
        self.main_view.common_phrases = list(self.phrases)
        # 同步到引擎 (对齐 Qt 版 _open_phrases_manager 行为)
        if hasattr(self.main_view.engine, "common_phrases"):
            self.main_view.engine.common_phrases = list(self.phrases)
        if hasattr(self.main_view.engine, "save_common_phrases_to_disk"):
            self.main_view.engine.save_common_phrases_to_disk()
        self.main_view.page.pop_dialog()

    def _persist(self):
        import json
        from pathlib import Path
        try:
            Path(get_common_phrases_path()).write_text(
                json.dumps(self.phrases, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass


class ShortcutsDialog(ft.AlertDialog):
    """快捷键帮助对话框"""

    def __init__(self, main_view):
        shortcuts = [
            (_("常用操作"), [
                (_("撤销"), "Ctrl+Z"),
                (_("重做"), "Ctrl+Shift+Z"),
                (_("打开项目"), "Ctrl+O"),
                (_("保存项目"), "Ctrl+S"),
                (_("清空列表"), "Ctrl+N"),
                (_("添加外部文件"), "Ctrl+E"),
            ]),
            (_("列表操作"), [
                (_("上方插入文本"), "Ctrl+I"),
                (_("下方插入文本"), "Ctrl+Shift+I"),
                (_("上移"), "Ctrl+Up"),
                (_("下移"), "Ctrl+Down"),
                (_("删除"), "Delete"),
                (_("生成合并文本"), "Ctrl+G"),
                (_("生成到剪贴板"), "Ctrl+Shift+C"),
            ]),
            (_("应用程序"), [
                (_("语言设置"), "Ctrl+,"),
                (_("键盘快捷键"), "Ctrl+/"),
                (_("关于"), "F1"),
            ]),
        ]

        content_controls = []
        for group_name, items in shortcuts:
            content_controls.append(
                ft.Text(group_name, weight=ft.FontWeight.BOLD, size=14)
            )
            for name, shortcut in items:
                content_controls.append(
                    ft.Row(
                        [
                            ft.Text(name, size=13, expand=True),
                            ft.Text(shortcut, size=13,
                                    weight=ft.FontWeight.W_600),
                        ],
                        spacing=16,
                    )
                )
            content_controls.append(ft.Divider())

        super().__init__(
            title=ft.Text(_("键盘快捷键")),
            content=ft.Column(
                content_controls,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
                height=400,
            ),
            actions=[
                ft.TextButton(
                    _("关闭"), on_click=lambda _: main_view.page.pop_dialog()),
            ],
        )


class TextEditDialog(ft.AlertDialog):
    """文字编辑对话框.

    对齐 Qt 版 TextEditDialog:
    - 支持多行输入
    - 提供"常用语"按钮, 弹出选择器后可一键填入选中常用语
    """

    def __init__(self, main_view, insert_index: int = None, edit_index: int = None,
                 show_phrases_button: bool = True):
        self.main_view = main_view
        self.insert_index = insert_index
        self.edit_index = edit_index

        initial_text = ""
        if edit_index is not None and 0 <= edit_index < len(main_view.engine.items):
            data = main_view.engine.items[edit_index]
            if data.type == "text":
                initial_text = data.content

        self.text_field = ft.TextField(
            value=initial_text,
            multiline=True,
            min_lines=6,
            max_lines=12,
            label=_("请输入文字:"),
        )

        # 内容区: 文本框 + (可选) 常用语按钮
        content_controls = [self.text_field]
        if show_phrases_button:
            self.btn_phrases = ft.ElevatedButton(
                _("常用语"),
                icon=ft.Icons.CHAT,
                on_click=self._on_open_phrases,
            )
            content_controls.append(
                ft.Row(
                    [self.btn_phrases],
                    alignment=ft.MainAxisAlignment.START,
                )
            )

        super().__init__(
            title=ft.Text(
                _("编辑文字") if edit_index is not None else _("插入自定义文字")),
            content=ft.Column(
                content_controls,
                tight=True,
            ),
            actions=[
                ft.TextButton(_("取消"), on_click=self._on_cancel),
                ft.TextButton(_("确定"), on_click=self._on_accept),
            ],
        )

    def _on_open_phrases(self, e):
        """打开常用语选择器 (select_mode=True).

        选中短语后只把它回填到自定义文字框, 并关闭常用语弹窗; 不自动触发插入.
        最终由用户点击自定义文字弹窗的确定/取消来关闭主弹窗.
        """
        def on_phrase_selected(phrase):
            if phrase:
                self.text_field.value = phrase
                self.text_field.update()

        phrases_dlg = PhrasesDialog(
            self.main_view,
            select_mode=True,
            on_phrase_selected=on_phrase_selected,
        )
        self.main_view.page.show_dialog(phrases_dlg)

    def _on_accept(self, e):
        text = self.text_field.value.strip()
        if not text:
            self._close()
            return

        if self.edit_index is not None:
            # 编辑模式
            data = self.main_view.engine.items[self.edit_index]
            if data.type == "text":
                self.main_view._push_undo()
                data.content = text
                data.update_token_stats()
                show_snack(self.main_view.page, _("文字已更新"))
        elif self.insert_index is not None:
            # 插入模式
            self.main_view._push_undo()
            self.main_view.engine.add_text(text, index=self.insert_index)
            show_snack(self.main_view.page, _("已插入文字"))

        self.main_view.arrangement_panel.refresh()
        self._close()

    def _on_cancel(self, e):
        self._close()

    def _close(self):
        """关闭当前 TextEditDialog."""
        try:
            self.main_view.page.pop_dialog()
        except Exception:
            pass
