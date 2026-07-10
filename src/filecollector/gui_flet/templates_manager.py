"""提示词模板管理对话框"""

from __future__ import annotations

import time

import flet as ft

from filecollector.i18n import _
from filecollector.config import (
    load_templates,
    save_templates,
    get_default_templates,
)
from filecollector.gui_flet.buttons import (
    primary_btn, secondary_btn, danger_btn, danger_text_btn,
)


class TemplatesManagerDialog(ft.AlertDialog):
    """提示词模板管理对话框.

    提供模板列表浏览、新增、编辑、删除功能。
    每个模板包含: id, name, description, header_text, footer_text, ai_prompt。
    """

    _FIELDS = [
        ("id", "ID", False),
        ("name", "模板名称", True),
        ("description", "描述", False),
        ("header_text", "头部文本", True),
        ("footer_text", "尾部文本", True),
        ("ai_prompt", "AI 提示词", True),
    ]

    def __init__(self, main_view):
        self.main_view = main_view
        self.templates: list[dict] = load_templates()
        self.selected_index: int = -1
        self._last_click_idx: int = -1
        self._last_click_ts: float = 0.0

        self.list_view = ft.ListView(expand=True, spacing=2)

        self.btn_edit = primary_btn(
            _("编辑"),
            icon=ft.Icons.EDIT,
            on_click=self._on_edit,
            disabled=True,
        )
        self.btn_delete = danger_btn(
            _("删除"),
            icon=ft.Icons.DELETE,
            on_click=self._on_delete,
            disabled=True,
        )

        actions_row = ft.Row(
            [
                primary_btn(
                    _("添加"),
                    icon=ft.Icons.ADD,
                    on_click=self._on_add,
                ),
                self.btn_edit,
                self.btn_delete,
            ],
            alignment=ft.MainAxisAlignment.START,
        )

        super().__init__(
            title=ft.Text(_("提示词模板管理")),
            content=ft.Column(
                [
                    ft.Container(
                        content=self.list_view,
                        height=280,
                        padding=ft.Padding(left=4, top=4, right=4, bottom=4),
                    ),
                    actions_row,
                ],
                tight=True,
            ),
            actions=[
                secondary_btn(_("关闭"), on_click=self._on_close),
            ],
        )

        self._refresh_list()

    def _refresh_list(self):
        self.list_view.controls.clear()
        if not self.templates:
            self.list_view.controls.append(
                ft.Container(
                    content=ft.Text(_("暂无模板"), color=ft.Colors.GREY_600),
                    padding=12,
                    alignment=ft.alignment.Alignment(0, 0),
                )
            )
            self._set_actions_enabled(False)
        else:
            for idx, tpl in enumerate(self.templates):
                is_selected = idx == self.selected_index
                name = tpl.get("name", tpl.get("id", ""))
                desc = tpl.get("description", "")
                display = f"{name} — {desc}" if desc else name
                if len(display) > 60:
                    display = display[:60] + "..."
                self.list_view.controls.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(
                                    display,
                                    size=14,
                                    expand=True,
                                    no_wrap=True,
                                    tooltip=name,
                                    color=ft.Colors.WHITE if is_selected else None,
                                ),
                            ],
                        ),
                        padding=ft.Padding(left=10, top=8, right=10, bottom=8),
                        border_radius=6,
                        bgcolor=(
                            ft.Colors.BLUE_600
                            if is_selected
                            else ft.Colors.SURFACE_CONTAINER_LOW
                        ),
                        on_click=lambda e, i=idx: self._on_item_click(i),
                        ink=True,
                    )
                )
            self._set_actions_enabled(self.selected_index >= 0)
        self.main_view.page.update()

    def _set_actions_enabled(self, enabled: bool):
        self.btn_edit.disabled = not enabled
        self.btn_delete.disabled = not enabled

    def _on_item_click(self, idx: int):
        now = time.monotonic()
        if idx == self._last_click_idx and now - self._last_click_ts < 0.3:
            self._last_click_idx = -1
            self._last_click_ts = 0.0
            self._on_double_click(idx)
            return
        self._last_click_idx = idx
        self._last_click_ts = now
        self._on_select(idx)

    def _on_select(self, idx: int):
        self.selected_index = idx
        self._refresh_list()

    def _on_double_click(self, idx: int):
        self.selected_index = idx
        self._refresh_list()
        self._on_edit(None)

    def _on_add(self, e):
        self._open_edit_dialog(_("新增模板"), None)

    def _on_edit(self, e):
        if not (0 <= self.selected_index < len(self.templates)):
            return
        self._open_edit_dialog(_("编辑模板"), self.templates[self.selected_index])

    def _open_edit_dialog(self, title: str, template: dict | None):
        fields: dict[str, ft.TextField] = {}
        for key, label, multiline in self._FIELDS:
            default_val = template.get(key, "") if template else ""
            if key == "id" and template is None:
                default_val = ""
            fields[key] = ft.TextField(
                value=default_val,
                label=label,
                multiline=multiline,
                min_lines=2 if multiline else None,
                max_lines=6 if multiline else None,
                read_only=(key == "id" and template is not None),
            )

        def on_submit(ev):
            new_tpl: dict[str, str] = {}
            for key, _, _ in self._FIELDS:
                new_tpl[key] = (fields[key].value or "").strip()
            if not new_tpl["id"]:
                return
            if template is not None:
                idx = self.templates.index(template)
                self.templates[idx] = new_tpl
                self.selected_index = idx
            else:
                self.templates.append(new_tpl)
                self.selected_index = len(self.templates) - 1
            self._persist()
            self._refresh_list()
            self.main_view.page.pop_dialog()

        dlg = ft.AlertDialog(
            title=ft.Text(title),
            content=ft.Column(
                list(fields.values()),
                tight=True,
                scroll=ft.ScrollMode.AUTO,
                height=380,
            ),
            actions=[
                secondary_btn(
                    _("取消"),
                    on_click=lambda _: self.main_view.page.pop_dialog(),
                ),
                primary_btn(_("确定"), on_click=on_submit),
            ],
        )
        self.main_view.page.show_dialog(dlg)

    def _on_delete(self, e):
        if not (0 <= self.selected_index < len(self.templates)):
            return

        def on_confirm(ev):
            self.main_view.page.pop_dialog()
            if 0 <= self.selected_index < len(self.templates):
                self.templates.pop(self.selected_index)
                self.selected_index = min(
                    self.selected_index, len(self.templates) - 1
                )
                self._persist()
                self._refresh_list()

        def on_cancel(ev):
            self.main_view.page.pop_dialog()

        confirm_dlg = ft.AlertDialog(
            title=ft.Text(_("确认")),
            content=ft.Text(_("删除选中模板？")),
            actions=[
                secondary_btn(_("取消"), on_click=on_cancel),
                secondary_btn(_("确定"), on_click=on_confirm),
            ],
        )
        self.main_view.page.show_dialog(confirm_dlg)

    def _on_close(self, e):
        self.main_view.page.pop_dialog()

    def _persist(self):
        save_templates(self.templates)
