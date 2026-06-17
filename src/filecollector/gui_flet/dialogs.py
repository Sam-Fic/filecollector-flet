"""对话框组件"""

from __future__ import annotations

import flet as ft

from filecollector.i18n import _
from filecollector.config import load_settings, save_settings, get_common_phrases_path
from filecollector.gui_flet.ai_settings_dialog import AISettingsDialog
from filecollector.gui_flet.snack import show_snack


class SettingsDialog(ft.AlertDialog):
    """语言设置对话框"""

    def __init__(self, main_view):
        self.main_view = main_view
        super().__init__(
            title=ft.Text(_("设置界面语言")),
            content=ft.Column(
                [
                    ft.Text(_("选择后立即生效。"), color=ft.Colors.GREY_600),
                    ft.Divider(),
                    ft.RadioGroup(
                        content=ft.Column(
                            [
                                ft.Radio(value="", label=_("跟随系统")),
                                ft.Radio(value="zh_CN", label="中文"),
                                ft.Radio(value="en", label="English"),
                            ]
                        ),
                        value=self._get_current_language(),
                        on_change=self._on_language_change,
                    ),
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
        lang = self.content.controls[2].value
        settings = load_settings()
        settings["language"] = lang
        save_settings(settings)

        # 提示重启
        from filecollector.i18n import set_language
        set_language(lang, notify=True)

        self.main_view.page.pop_dialog()
        show_snack(self.main_view.page, _("语言设置已保存，重启应用后生效。"))

    def _on_cancel(self, e):
        self.main_view.page.pop_dialog()


class PhrasesDialog(ft.AlertDialog):
    """常用语管理对话框"""

    def __init__(self, main_view):
        self.main_view = main_view
        self.phrases = list(main_view.common_phrases)
        self.selected_index: int = -1

        self.list_view = ft.ListView(
            expand=True,
            spacing=4,
        )

        self.btn_delete = ft.ElevatedButton(
            _("删除"),
            icon=ft.Icons.DELETE,
            color=ft.Colors.WHITE,
            bgcolor=ft.Colors.RED_600,
            on_click=self._on_delete,
            disabled=True,
        )

        super().__init__(
            title=ft.Text(_("常用语管理")),
            content=ft.Column(
                [
                    ft.Container(
                        content=self.list_view,
                        expand=True,
                        height=300,
                    ),
                    ft.Row(
                        [
                            ft.ElevatedButton(
                                _("添加"),
                                icon=ft.Icons.ADD,
                                on_click=self._on_add,
                            ),
                            self.btn_delete,
                        ],
                        alignment=ft.MainAxisAlignment.START,
                    ),
                ],
                tight=True,
            ),
            actions=[
                ft.TextButton(_("关闭"), on_click=self._on_close),
            ],
        )

        self._refresh_list()

    def _refresh_list(self):
        self.list_view.controls.clear()
        if not self.phrases:
            self.list_view.controls.append(
                ft.Text(_("暂无常用语"), color=ft.Colors.GREY_600)
            )
            self.btn_delete.disabled = True
        else:
            for idx, phrase in enumerate(self.phrases):
                is_selected = idx == self.selected_index
                self.list_view.controls.append(
                    ft.Container(
                        content=ft.Text(phrase, size=14),
                        padding=8,
                        border_radius=4,
                        bgcolor=ft.Colors.BLUE_100 if is_selected else ft.Colors.SURFACE_CONTAINER_LOW,
                        on_click=lambda e, i=idx: self._on_select(i),
                        ink=True,
                    )
                )
            self.btn_delete.disabled = self.selected_index < 0
        self.main_view.page.update()

    def _on_add(self, e):
        def on_submit(e):
            text = self.text_field.value.strip()
            if text:
                self.phrases.append(text)
                self.selected_index = len(self.phrases) - 1
                self._persist()
                self._refresh_list()
            self.main_view.page.pop_dialog()

        self.text_field = ft.TextField(
            label=_("新增常用语"),
            multiline=True,
            min_lines=2,
            max_lines=4,
        )

        dlg = ft.AlertDialog(
            title=ft.Text(_("新增常用语")),
            content=self.text_field,
            actions=[
                ft.TextButton(
                    _("取消"), on_click=lambda _: self.main_view.page.pop_dialog()),
                ft.TextButton(_("确定"), on_click=on_submit),
            ],
        )
        self.main_view.page.show_dialog(dlg)

    def _on_delete(self, e):
        if 0 <= self.selected_index < len(self.phrases):
            self.phrases.pop(self.selected_index)
            self.selected_index = min(self.selected_index, len(self.phrases) - 1)
            self._persist()
            self._refresh_list()
            self._persist()
            self._refresh_list()

    def _on_select(self, idx: int):
        self.selected_index = idx
        self._refresh_list()

    def _on_close(self, e):
        self.main_view.common_phrases = self.phrases
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
                (_("退出"), "Ctrl+Q"),
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
    """文字编辑对话框"""

    def __init__(self, main_view, insert_index: int = None, edit_index: int = None):
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

        super().__init__(
            title=ft.Text(
                _("编辑文字") if edit_index is not None else _("插入自定义文字")),
            content=self.text_field,
            actions=[
                ft.TextButton(_("取消"), on_click=self._on_cancel),
                ft.TextButton(_("确定"), on_click=self._on_accept),
            ],
        )

    def _on_accept(self, e):
        text = self.text_field.value.strip()
        if not text:
            self.main_view.page.pop_dialog()
            return

        if self.edit_index is not None:
            # 编辑模式
            data = self.main_view.engine.items[self.edit_index]
            if data.type == "text":
                data.content = text
                show_snack(self.main_view.page, _("文字已更新"))
        elif self.insert_index is not None:
            # 插入模式
            self.main_view._push_undo()
            self.main_view.engine.add_text(text, index=self.insert_index)
            show_snack(self.main_view.page, _("已插入文字"))

        self.main_view.arrangement_panel.refresh()
        self.main_view.page.pop_dialog()

    def _on_cancel(self, e):
        self.main_view.page.pop_dialog()
