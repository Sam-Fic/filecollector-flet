"""编排列表面板 - 中间面板"""

from __future__ import annotations

import time
from pathlib import Path

import flet as ft

from filecollector.models import ItemData
from filecollector.i18n import _
from filecollector.gui_flet.dialogs import TextEditDialog
from filecollector.gui_flet.snack import show_snack


class ArrangementListPanel:
    """中间编排列表面板"""

    def __init__(self, main_view):
        self.main_view = main_view
        self.selected_index: int = -1
        # 双击检测
        self._last_click_idx: int = -1
        self._last_click_ts: float = 0.0

        self._build_ui()

    def _build_ui(self):
        """构建列表面板 UI"""
        # 列表视图
        self.list_view = ft.ListView(
            expand=True,
            spacing=4,
            padding=ft.Padding(left=12, right=12, top=0, bottom=12),
        )

        # 按钮行 1
        self.btn_insert_above = ft.ElevatedButton(
            _("上方插入文本"),
            icon=ft.Icons.ARROW_UPWARD,
            on_click=self._on_insert_text_above,
            disabled=True,
            col={"xs": 12, "sm": 4},
        )
        self.btn_insert_below = ft.ElevatedButton(
            _("下方插入文本"),
            icon=ft.Icons.ARROW_DOWNWARD,
            on_click=self._on_insert_text_below,
            disabled=True,
            col={"xs": 12, "sm": 4},
        )
        btn_row1 = ft.ResponsiveRow(
            [
                ft.ElevatedButton(
                    _("添加外部文件"),
                    icon=ft.Icons.FILE_UPLOAD,
                    on_click=self._on_add_external,
                    col={"xs": 12, "sm": 4},
                ),
                self.btn_insert_above,
                self.btn_insert_below,
            ],
        )

        # 按钮行 2
        self.btn_move_up = ft.IconButton(
            icon=ft.Icons.ARROW_UPWARD,
            tooltip=_("上移"),
            on_click=self._on_move_up,
            disabled=True,
        )
        self.btn_move_down = ft.IconButton(
            icon=ft.Icons.ARROW_DOWNWARD,
            tooltip=_("下移"),
            on_click=self._on_move_down,
            disabled=True,
        )
        self.btn_delete = ft.IconButton(
            icon=ft.Icons.DELETE,
            tooltip=_("删除"),
            on_click=self._on_delete,
            disabled=True,
        )
        btn_row2 = ft.ResponsiveRow(
            [
                ft.Row(
                    [self.btn_move_up, self.btn_move_down, self.btn_delete],
                    spacing=8,
                    col={"xs": 12, "sm": 6},
                ),
                ft.Row(
                    [
                        ft.ElevatedButton(
                            _("清空"),
                            icon=ft.Icons.CLEAR_ALL,
                            color=ft.Colors.WHITE,
                            bgcolor=ft.Colors.RED_600,
                            on_click=self._on_clear,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.END,
                    col={"xs": 12, "sm": 6},
                ),
            ],
        )

        # 路径模式选项
        self.path_mode_group = ft.RadioGroup(
            content=ft.Row(
                [
                    ft.Radio(value="relative", label=_("相对路径"),
                             visual_density=ft.VisualDensity.COMPACT),
                    ft.Radio(value="absolute", label=_("使用绝对路径"),
                             visual_density=ft.VisualDensity.COMPACT),
                ],
                spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            value="relative" if not self.main_view.engine.use_absolute else "absolute",
            on_change=self._on_path_mode_change,
        )
        self.check_header = ft.Checkbox(
            label=_("在文件头部标注工作目录信息"),
            on_change=self._on_header_change,
            visual_density=ft.VisualDensity.COMPACT,
        )

        opt_row = ft.Row(
            [
                self.path_mode_group,
                self.check_header,
            ],
            spacing=16,
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=True,
        )

        # 按钮行 3 - 生成
        btn_row3 = ft.ResponsiveRow(
            [
                ft.ElevatedButton(
                    _("生成合并文本"),
                    icon=ft.Icons.SAVE_ALT,
                    color=ft.Colors.WHITE,
                    bgcolor=ft.Colors.BLUE_600,
                    on_click=self._on_generate_txt,
                    col={"xs": 12, "sm": 6},
                ),
                ft.ElevatedButton(
                    _("生成到剪贴板"),
                    icon=ft.Icons.CONTENT_COPY,
                    color=ft.Colors.WHITE,
                    bgcolor=ft.Colors.BLUE_600,
                    on_click=self._on_generate_clipboard,
                    col={"xs": 12, "sm": 6},
                ),
            ],
        )

        # 面板容器
        self.container = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Text(
                            _("输出编排列表"),
                            weight=ft.FontWeight.BOLD,
                            size=16,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        padding=ft.Padding(top=10, bottom=10, left=0, right=0),
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Container(
                        content=self.list_view,
                        expand=True,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [btn_row1, btn_row2, opt_row, btn_row3],
                            spacing=8,
                        ),
                        padding=ft.Padding(
                            left=12, right=12, bottom=8, top=0),
                    ),
                ],
                spacing=0,
                expand=True,
            ),
            expand=2,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border_radius=12,
            padding=0,
        )

    def refresh(self):
        """刷新列表"""
        self.list_view.controls.clear()

        for idx, data in enumerate(self.main_view.engine.items):
            display = self._get_display_text(idx, data)

            # 创建列表项
            item = ft.Container(
                content=ft.Row(
                    [
                        ft.Text(
                            display,
                            size=14,
                            expand=True,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.Padding(left=12, top=8, right=12, bottom=8),
                border_radius=8,
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOW
                if idx == self.selected_index else None,
                on_click=lambda e, i=idx: self._on_item_click(i),
                on_hover=lambda e, i=idx: self._on_item_hover(e, i),
                ink=True,
            )

            self.list_view.controls.append(item)

        # 更新单选框状态
        self.path_mode_group.value = "absolute" if self.main_view.engine.use_absolute else "relative"
        self.check_header.value = self.main_view.engine.show_header
        self.check_header.disabled = self.main_view.engine.use_absolute

        self._update_button_states()
        self.main_view.page.update()

    def _update_button_states(self):
        """更新按钮启用/禁用状态"""
        has_sel = 0 <= self.selected_index < len(self.main_view.engine.items)
        has_items = len(self.main_view.engine.items) > 0

        self.btn_insert_above.disabled = not has_sel
        self.btn_insert_below.disabled = not has_sel
        self.btn_delete.disabled = not has_sel
        self.btn_move_up.disabled = not has_sel or self.selected_index == 0
        self.btn_move_down.disabled = not has_sel or self.selected_index >= len(
            self.main_view.engine.items) - 1

    def _get_display_text(self, idx: int, data: ItemData) -> str:
        """获取列表项显示文本"""
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

    def _on_item_click(self, idx: int):
        """列表项点击: 检测双击 (同一条目 300ms 内两次点击)."""
        now = time.monotonic()
        if (idx == self._last_click_idx
                and now - self._last_click_ts < 0.3):
            # 双击 -> 编辑文本
            self._last_click_idx = -1
            self._last_click_ts = 0.0
            self._on_item_double_click(idx)
            return
        # 单击 -> 选中
        self._last_click_idx = idx
        self._last_click_ts = now
        self.selected_index = idx
        if 0 <= idx < len(self.main_view.engine.items):
            data = self.main_view.engine.items[idx]
            self.main_view.show_preview(data)
        self.refresh()

    def _on_item_double_click(self, idx: int):
        """列表项双击编辑"""
        if 0 <= idx < len(self.main_view.engine.items):
            data = self.main_view.engine.items[idx]
            if data.type == "text":
                dlg = TextEditDialog(
                    self.main_view, edit_index=idx,
                    show_phrases_button=False,
                )
                self.main_view.page.show_dialog(dlg)

    def _on_item_hover(self, e: ft.HoverEvent, idx: int):
        """列表项悬停"""
        pass

    def _on_add_external(self, e):
        """添加外部文件"""

        async def pick():
            files = await self.main_view._file_picker.pick_files(
                dialog_title=_("选择外部文件"),
                allow_multiple=True,
            )
            if files:
                self.main_view._push_undo()
                for f in files:
                    abs_path = str(Path(f.path).resolve())
                    self.main_view.engine.add_file(
                        abs_path, force_absolute=True)
                self.refresh()
                show_snack(self.main_view.page,
                           _("已添加 %d 个外部文件") % len(files))

        self.main_view.page.run_task(pick)

    def _on_insert_text_above(self, e):
        """上方插入文本"""
        if self.selected_index < 0:
            show_snack(self.main_view.page, _("请先选择一个条目"))
            return

        dlg = TextEditDialog(self.main_view, insert_index=self.selected_index)
        self.main_view.page.show_dialog(dlg)

    def _on_insert_text_below(self, e):
        """下方插入文本"""
        if self.selected_index < 0:
            show_snack(self.main_view.page, _("请先选择一个条目"))
            return

        dlg = TextEditDialog(
            self.main_view, insert_index=self.selected_index + 1)
        self.main_view.page.show_dialog(dlg)

    def _on_move_up(self, e):
        """上移"""
        if self.selected_index > 0:
            self.main_view._push_undo()
            self.main_view.engine.move_item(
                self.selected_index, self.selected_index - 1)
            self.selected_index -= 1
            self.refresh()

    def _on_move_down(self, e):
        """下移"""
        if 0 <= self.selected_index < len(self.main_view.engine.items) - 1:
            self.main_view._push_undo()
            self.main_view.engine.move_item(
                self.selected_index, self.selected_index + 1)
            self.selected_index += 1
            self.refresh()

    def _on_delete(self, e):
        """删除"""
        if self.selected_index >= 0:
            self.main_view._push_undo()
            data = self.main_view.engine.items[self.selected_index]
            if data.type == "file" and not data.force_absolute:
                if data.path in self.main_view.engine.checked_paths:
                    self.main_view.engine.checked_paths.discard(data.path)
                    self.main_view.file_tree_panel.checked_paths.discard(
                        data.path)
            self.main_view.engine.remove_item(self.selected_index)
            self.selected_index = -1
            self.refresh()
            show_snack(self.main_view.page, _("条目已删除"))

    def _on_clear(self, e):
        """清空列表"""
        def on_confirm(e):
            if e.control.data == "yes":
                self.main_view._push_undo()
                for path in list(self.main_view.engine.checked_paths):
                    self.main_view.file_tree_panel.checked_paths.discard(path)
                self.main_view.engine.clear()
                self.selected_index = -1
                self.refresh()
                show_snack(self.main_view.page, _("编排列表已清空"))
            self.main_view.page.pop_dialog()

        dlg = ft.AlertDialog(
            title=ft.Text(_("确认")),
            content=ft.Text(_("确定清空编排列表吗？")),
            actions=[
                ft.TextButton(_("取消"), on_click=on_confirm, data="no"),
                ft.TextButton(_("确定"), on_click=on_confirm, data="yes"),
            ],
        )
        self.main_view.page.show_dialog(dlg)

    def _on_path_mode_change(self, e):
        """路径模式切换"""
        self.main_view._push_undo()
        self.main_view.engine.use_absolute = (
            self.path_mode_group.value == "absolute")
        self.refresh()

    def _on_header_change(self, e):
        """头部信息切换"""
        self.main_view.engine.show_header = self.check_header.value

    def _on_generate_txt(self, e):
        """生成 TXT 文件"""
        if not self.main_view.engine.items:
            show_snack(self.main_view.page, _("编排列表为空，无法生成。"))
            return

        async def pick():
            path = await self.main_view._file_picker.save_file(
                dialog_title=_("保存合并文本"),
                file_name="merged.txt",
            )
            if path:
                if not path.lower().endswith('.txt'):
                    path += '.txt'
                try:
                    self.main_view.engine.export(path)
                    show_snack(self.main_view.page, _("TXT 已生成: %s") % path)
                    # 在文件管理器中显示生成的文件 (对齐 Qt 版行为)
                    self.main_view.open_file_location(path)
                except Exception as ex:
                    show_snack(self.main_view.page, _("生成失败: %s") % ex)

        self.main_view.page.run_task(pick)

    def _on_generate_clipboard(self, e):
        """生成到剪贴板"""
        if not self.main_view.engine.items:
            show_snack(self.main_view.page, _("编排列表为空，无法生成。"))
            return

        try:
            from filecollector.config import get_clipboard_staging_path
            import subprocess
            import sys

            file_path = get_clipboard_staging_path()
            self.main_view.engine.export(file_path)

            if sys.platform == "win32":
                subprocess.run(
                    ["clip"],
                    input=open(file_path, "rb").read(),
                    check=False,
                )
            else:
                subprocess.run(
                    ["xclip", "-selection", "clipboard", file_path],
                    check=False,
                )

            show_snack(self.main_view.page, _("合并文本已复制到剪贴板"))
        except Exception as ex:
            show_snack(self.main_view.page, _("复制到剪贴板失败: %s") % ex)

    def sync_from_tree(self):
        """从文件树同步状态"""
        # 更新 engine 的 checked_paths
        self.main_view.engine.checked_paths = self.main_view.file_tree_panel.checked_paths.copy()

        # 重建 items 中的文件项
        from filecollector.models import ItemData as _ID
        checked_now = set(self.main_view.engine.checked_paths)
        checked_prev: set[str] = set()
        for it in self.main_view.engine.items:
            if it.type == "file" and not it.force_absolute:
                checked_prev.add(it.path)

        # 添加新勾选的文件
        for path in checked_now - checked_prev:
            self.main_view.engine.items.append(
                _ID(type_="file", path=path, force_absolute=False)
            )

        # 移除取消勾选的文件
        for path in checked_prev - checked_now:
            self.main_view.engine.items = [
                it for it in self.main_view.engine.items
                if not (it.type == "file" and it.path == path and not it.force_absolute)
            ]
