"""编排列表面板 - 中间面板.

Flet 版本 - 复刻 GNOME 版 arragement_list 的核心交互, 同时引入多模态预处理:
- 显示文件/文本条目, 支持单击选中, 双击编辑
- 二进制条目右侧显示预处理状态徽标 (PENDING / CHECKING / PROCESSING / COMPLETED / FAILED)
- 右键菜单 (secondary click) 提供:
    * 重新进行 AI 转换 (仅 binary)
    * 复制路径
    * 在文件管理器中显示 (仅 file)
    * 上移 / 下移 / 删除 / 清空等编辑操作
- 拖动排序: 使用 long_press + drag 模拟 (Flet 无原生 DragWidget onRow,
  采用"长按进入拖动模式 -> 上下移动按钮高亮" 的简化交互).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import flet as ft

from filecollector.models import ItemData, PreprocessStatus
from filecollector.i18n import _
from filecollector.gui_flet.dialogs import TextEditDialog
from filecollector.gui_flet.snack import show_snack


# ============================================================ 状态徽标样式
_STATUS_BADGE_COLORS: dict[int, tuple[str, str]] = {
    # status -> (bg_color, fg_color)
    PreprocessStatus.PENDING:    ("#FFF3CD", "#856404"),  # 等待处理 - 琥珀
    PreprocessStatus.CHECKING:   ("#D1ECF1", "#0C5460"),  # 检查缓存 - 浅蓝
    PreprocessStatus.PROCESSING: ("#D6E4FF", "#1E3A8A"),  # 处理中 - 蓝
    PreprocessStatus.COMPLETED:  ("#D4EDDA", "#155724"),  # 完成 - 绿
    PreprocessStatus.FAILED:     ("#F8D7DA", "#721C24"),  # 失败 - 红
}

_STATUS_BADGE_LABELS: dict[int, str] = {
    PreprocessStatus.PENDING:    "等待处理",
    PreprocessStatus.CHECKING:   "检查缓存…",
    PreprocessStatus.PROCESSING: "AI 转换中…",
    PreprocessStatus.COMPLETED:  "已转换",
    PreprocessStatus.FAILED:     "转换失败",
}


class ArrangementListPanel:
    """中间编排列表面板"""

    def __init__(self, main_view):
        self.main_view = main_view
        self.selected_index: int = -1
        # 双击检测
        self._last_click_idx: int = -1
        self._last_click_ts: float = 0.0
        # 当前打开的右键菜单 (用于关闭)
        self._open_ctx_menu: Optional[ft.AlertDialog] = None

        self._build_ui()

    def _build_ui(self):
        """构建列表面板 UI"""
        # 列表视图
        self.list_view = ft.ListView(
            expand=True,
            spacing=4,
            padding=ft.Padding(left=12, right=12, top=0, bottom=0),
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
                    ft.Radio(value="relative", label=_("使用相对路径"),
                             visual_density=ft.VisualDensity.COMPACT),
                    ft.Radio(value="absolute", label=_("使用绝对路径"),
                             visual_density=ft.VisualDensity.COMPACT),
                ],
                spacing=16,
                alignment=ft.MainAxisAlignment.CENTER,
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

        opt_row = ft.Column(
            [
                self.path_mode_group,
                ft.Row(
                    [self.check_header],
                    alignment=ft.MainAxisAlignment.CENTER,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
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

    # =============================================================== 列表渲染
    def refresh(self):
        """刷新列表"""
        self.list_view.controls.clear()

        for idx, data in enumerate(self.main_view.engine.items):
            self.list_view.controls.append(self._build_list_row(idx, data))

        # 更新单选框状态
        self.path_mode_group.value = "absolute" if self.main_view.engine.use_absolute else "relative"
        self.check_header.value = self.main_view.engine.show_header
        self.check_header.disabled = self.main_view.engine.use_absolute

        self._update_button_states()
        try:
            self.main_view.page.update()
        except Exception:
            pass

    def _build_list_row(self, idx: int, data: ItemData) -> ft.Container:
        """构建单条列表项 UI."""
        is_selected = idx == self.selected_index
        # 主显示行
        primary = self._get_display_text(idx, data)
        # 二进制预处理徽标
        badge = self._build_status_badge(data)

        leading_icon = self._get_item_icon(data)

        # 右侧: 状态徽标 + 路径提示
        right_controls: list[ft.Control] = []
        if badge is not None:
            right_controls.append(badge)

        # 主行
        row = ft.Row(
            [
                ft.Icon(leading_icon, size=18, color=self._get_item_icon_color(data)),
                ft.Text(
                    primary,
                    size=14,
                    expand=True,
                    no_wrap=False,
                ),
                *right_controls,
            ],
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
        )

        inner = ft.Container(
            content=row,
            padding=ft.Padding(left=12, top=8, right=12, bottom=8),
            border_radius=8,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW if is_selected else None,
            on_click=lambda e, i=idx: self._on_item_click(i),
            on_hover=lambda e, i=idx: self._on_item_hover(e, i),
            tooltip=self._build_tooltip(data),
            ink=True,
            data=idx,
        )
        # Flet 的 ft.Container 不支持 on_secondary_click, 用 GestureDetector 包裹实现右键
        container = ft.GestureDetector(
            content=inner,
            on_secondary_tap=lambda e, i=idx: self._on_item_right_click(i, e),
        )
        return container

    def _build_status_badge(self, data: ItemData) -> Optional[ft.Container]:
        """根据预处理状态返回徽标控件; NONE / 非文件 / 非 binary 返回 None."""
        if data.type != "file" or not data.path:
            return None
        runner = getattr(self.main_view, "preprocess_runner", None)
        allowed = runner.get_allowed_exts() if runner else []
        if not data.is_allowed_binary_target(allowed):
            return None
        st = data.preprocess_status
        if st == PreprocessStatus.NONE:
            return None
        bg, fg = _STATUS_BADGE_COLORS.get(st, ("#E0E0E0", "#333333"))
        label = _STATUS_BADGE_LABELS.get(st, "?")
        return ft.Container(
            content=ft.Text(
                label,
                size=11,
                color=fg,
                weight=ft.FontWeight.W_500,
            ),
            bgcolor=bg,
            padding=ft.Padding(left=8, top=2, right=8, bottom=2),
            border_radius=10,
            tooltip=_("AI 预处理状态: %s") % label,
        )

    def _get_item_icon(self, data: ItemData) -> str:
        if data.type == "text":
            return ft.Icons.SUBJECT
        if not data.path:
            return ft.Icons.INSERT_DRIVE_FILE
        ext = Path(data.path).suffix.lower()
        if ext in (".pdf",):
            return ft.Icons.PICTURE_AS_PDF
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"):
            return ft.Icons.IMAGE
        if ext in (".doc", ".docx", ".odt", ".rtf", ".wps"):
            return ft.Icons.DESCRIPTION
        if ext in (".ppt", ".pptx", ".odp"):
            return ft.Icons.SLIDESHOW
        if ext in (".xls", ".xlsx", ".ods"):
            return ft.Icons.TABLE_CHART
        return ft.Icons.INSERT_DRIVE_FILE

    def _get_item_icon_color(self, data: ItemData) -> str:
        if data.type == "text":
            return ft.Colors.TEAL_600
        if not data.path:
            return ft.Colors.GREY_500
        ext = Path(data.path).suffix.lower()
        if ext == ".pdf":
            return ft.Colors.RED_600
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"):
            return ft.Colors.PURPLE_600
        if ext in (".doc", ".docx", ".odt", ".rtf", ".wps"):
            return ft.Colors.BLUE_600
        if ext in (".ppt", ".pptx", ".odp"):
            return ft.Colors.ORANGE_600
        if ext in (".xls", ".xlsx", ".ods"):
            return ft.Colors.GREEN_600
        return ft.Colors.GREY_500

    def _build_tooltip(self, data: ItemData) -> Optional[str]:
        if data.type == "file" and data.path:
            tip = data.path
            runner = getattr(self.main_view, "preprocess_runner", None)
            allowed = runner.get_allowed_exts() if runner else []
            if data.is_allowed_binary_target(allowed) and data.from_cache:
                tip += "\n" + _("已读取本地缓存")
            return tip
        return None

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
            preview = data.content or ""
            if len(preview) > 30:
                preview = preview[:30] + "..."
            return f"{idx+1}. {preview}"

    # =============================================================== 鼠标事件
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

    def _on_item_right_click(self, idx: int, e):
        """鼠标右键 - 弹出操作菜单."""
        if not (0 <= idx < len(self.main_view.engine.items)):
            return
        self.selected_index = idx
        # 同步显示选中态
        self.refresh()
        data = self.main_view.engine.items[idx]
        self._show_context_menu(idx, data)

    # =============================================================== 右键菜单
    def _show_context_menu(self, idx: int, data: ItemData) -> None:
        """弹出右键菜单 (使用 AlertDialog, 沿用最早期的简洁样式)."""
        # 关闭已存在的菜单
        if self._open_ctx_menu is not None:
            try:
                self.main_view.page.pop_dialog()
            except Exception:
                pass
            self._open_ctx_menu = None

        # 构建菜单项
        items: list[ft.Control] = []

        # 标题: 简要描述条目
        if data.type == "file" and data.path:
            title = f"{idx+1}. {Path(data.path).name}"
        elif data.type == "text":
            preview = (data.content or "")[:30]
            if len(data.content or "") > 30:
                preview += "…"
            title = f"{idx+1}. {preview}"
        else:
            title = f"{idx+1}."
        items.append(ft.Text(title, weight=ft.FontWeight.BOLD, size=14))
        items.append(ft.Divider(height=8, thickness=1))

        runner = getattr(self.main_view, "preprocess_runner", None)
        allowed = runner.get_allowed_exts() if runner else []
        is_binary = (data.type == "file" and data.is_allowed_binary_target(allowed))

        # 1. 重新进行 AI 转换
        if is_binary:
            items.append(self._menu_item(
                icon=ft.Icons.REFRESH,
                text=_("重新进行 AI 转换"),
                on_click=lambda e, i=idx: (
                    self._close_ctx_menu(),
                    self._on_retry_ai(i),
                ),
            ))

        # 2. 编辑文字 (仅文本条目)
        if data.type == "text":
            items.append(self._menu_item(
                icon=ft.Icons.EDIT,
                text=_("编辑文本"),
                on_click=lambda e, i=idx: (
                    self._close_ctx_menu(),
                    self._on_edit_text(i),
                ),
            ))

        # 3. 上方插入文本
        items.append(self._menu_item(
            icon=ft.Icons.ARROW_UPWARD,
            text=_("在上方插入文本"),
            on_click=lambda e, i=idx: (
                self._close_ctx_menu(),
                self._on_insert_above(i),
            ),
        ))
        # 4. 下方插入文本
        items.append(self._menu_item(
            icon=ft.Icons.ARROW_DOWNWARD,
            text=_("在下方插入文本"),
            on_click=lambda e, i=idx: (
                self._close_ctx_menu(),
                self._on_insert_below(i),
            ),
        ))
        # 5. 上移 / 下移
        items.append(self._menu_item(
            icon=ft.Icons.ARROW_UPWARD,
            text=_("上移"),
            on_click=lambda e, i=idx: (
                self._close_ctx_menu(),
                self._on_move_up_at(i),
            ),
        ))
        items.append(self._menu_item(
            icon=ft.Icons.ARROW_DOWNWARD,
            text=_("下移"),
            on_click=lambda e, i=idx: (
                self._close_ctx_menu(),
                self._on_move_down_at(i),
            ),
        ))

        # 6. 复制路径 (仅 file)
        if data.type == "file" and data.path:
            items.append(self._menu_item(
                icon=ft.Icons.CONTENT_COPY,
                text=_("复制路径"),
                on_click=lambda e, p=data.path: (
                    self._close_ctx_menu(),
                    self._on_copy_path(p),
                ),
            ))

        # 7. 在文件管理器中显示 (仅 file)
        if data.type == "file" and data.path:
            items.append(self._menu_item(
                icon=ft.Icons.FOLDER_OPEN,
                text=_("在文件管理器中显示"),
                on_click=lambda e, p=data.path: (
                    self._close_ctx_menu(),
                    self._on_show_in_folder(p),
                ),
            ))

        items.append(ft.Divider(height=8, thickness=1))

        # 8. 删除
        items.append(self._menu_item(
            icon=ft.Icons.DELETE_OUTLINE,
            text=_("删除"),
            color=ft.Colors.RED_600,
            on_click=lambda e, i=idx: (
                self._close_ctx_menu(),
                self._on_delete_at(i),
            ),
        ))

        # 回到最早期样式: 直接用 AlertDialog, 不加任何额外 padding/modal 控制
        # 四周统一 24px 内边距, 让菜单与对话框边缘留出合理的视觉空隙
        dlg = ft.AlertDialog(
            content=ft.Container(
                content=ft.Column(
                    items,
                    spacing=2,
                    tight=True,
                ),
                width=260,
                padding=ft.Padding(left=24, right=24, top=24, bottom=24),
            ),
            content_padding=ft.Padding(0, 0, 0, 0),
            actions_padding=ft.Padding(0, 0, 0, 0),
            actions=[],
        )
        self._open_ctx_menu = dlg
        try:
            self.main_view.page.show_dialog(dlg)
        except Exception:
            self._open_ctx_menu = None

    def _menu_item(self, icon: str, text: str,
                   on_click=None, color=None) -> ft.Control:
        """构建右键菜单中的一项."""
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, size=18, color=color or ft.Colors.GREY_700),
                    ft.Text(
                        text, size=13, expand=True,
                        color=color or None,
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=8, top=6, right=8, bottom=6),
            border_radius=6,
            on_click=on_click,
            ink=True,
        )

    def _close_ctx_menu(self):
        """关闭右键菜单 (AlertDialog 用 pop_dialog)."""
        if self._open_ctx_menu is not None:
            try:
                self.main_view.page.pop_dialog()
            except Exception:
                pass
            self._open_ctx_menu = None

    # =============================================================== 菜单动作
    def _on_retry_ai(self, idx: int):
        """强制重新调用多模态模型转换."""
        runner = getattr(self.main_view, "preprocess_runner", None)
        if not runner:
            show_snack(self.main_view.page, _("AI 助手未启用"))
            return
        if not (0 <= idx < len(self.main_view.engine.items)):
            return
        item = self.main_view.engine.items[idx]
        if item.type != "file":
            return
        runner.retry(item)
        show_snack(self.main_view.page, _("已重新触发 AI 转换"))

    def _on_edit_text(self, idx: int):
        dlg = TextEditDialog(
            self.main_view, edit_index=idx,
            show_phrases_button=False,
        )
        self.main_view.page.show_dialog(dlg)

    def _on_insert_above(self, idx: int):
        dlg = TextEditDialog(
            self.main_view, insert_index=idx,
        )
        self.main_view.page.show_dialog(dlg)

    def _on_insert_below(self, idx: int):
        dlg = TextEditDialog(
            self.main_view, insert_index=idx + 1,
        )
        self.main_view.page.show_dialog(dlg)

    def _on_move_up_at(self, idx: int):
        if idx > 0:
            self.main_view._push_undo()
            self.main_view.engine.move_item(idx, idx - 1)
            self.selected_index = idx - 1
            self.refresh()

    def _on_move_down_at(self, idx: int):
        if 0 <= idx < len(self.main_view.engine.items) - 1:
            self.main_view._push_undo()
            self.main_view.engine.move_item(idx, idx + 1)
            self.selected_index = idx + 1
            self.refresh()

    def _on_copy_path(self, path: str):
        try:
            self.main_view.page.set_clipboard(path)
            show_snack(self.main_view.page, _("路径已复制到剪贴板"))
        except Exception as ex:
            show_snack(self.main_view.page, _("复制失败: %s") % ex)

    def _on_show_in_folder(self, path: str):
        self.main_view.open_file_location(path)
        try:
            self.main_view.page.update()
        except Exception:
            pass

    def _on_delete_at(self, idx: int):
        if 0 <= idx < len(self.main_view.engine.items):
            self.main_view._push_undo()
            data = self.main_view.engine.items[idx]
            if data.type == "file" and not data.force_absolute:
                if data.path in self.main_view.engine.checked_paths:
                    self.main_view.engine.checked_paths.discard(data.path)
                    self.main_view.file_tree_panel.checked_paths.discard(
                        data.path)
            self.main_view.engine.remove_item(idx)
            self.selected_index = -1
            self.main_view.file_tree_panel.refresh()
            self.refresh()
            show_snack(self.main_view.page, _("条目已删除"))

    # =============================================================== 原始按钮事件
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
                self._after_items_changed()
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
            self._on_delete_at(self.selected_index)

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
                self._after_items_changed()
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
                with open(file_path, "rb") as f:
                    subprocess.run(
                        ["clip"],
                        input=f.read(),
                        check=False,
                    )
            elif sys.platform == "darwin":
                with open(file_path, "rb") as f:
                    subprocess.run(
                        ["pbcopy"],
                        input=f.read(),
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

    # =============================================================== 同步 / 外部
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

        # 触发新文件的预处理检查
        self._after_items_changed()

    def _after_items_changed(self):
        """编排列表新增 / 移除文件后, 触发对新增 binary 项的缓存检查."""
        runner = getattr(self.main_view, "preprocess_runner", None)
        if not runner:
            return
        try:
            runner.reevaluate_queue()
        except Exception as ex:
            import logging
            logging.warning(f"reevaluate_queue 失败: {ex}")

    def notify_preprocess_status_changed(self, item: ItemData):
        """由 main_view 调用: 某条目预处理状态变化, 局部刷新对应行."""
        try:
            # 整列表刷新最简单可靠; 量大后再考虑局部更新
            self.refresh()
        except Exception:
            pass
