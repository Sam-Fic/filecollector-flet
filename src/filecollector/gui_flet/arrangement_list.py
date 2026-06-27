"""编排列表面板 - 中间面板.

Flet 版本 - 复刻 GNOME 版 arragement_list 的核心交互, 同时引入 VLM 预处理:
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
from filecollector.utils import display_path
from filecollector.gui_flet.dialogs import TextEditDialog
from filecollector.gui_flet.snack import show_snack
from filecollector.gui_flet.buttons import (
    primary_btn, secondary_btn, danger_text_btn, icon_btn, PRIMARY,
)
from filecollector.gui_flet.context_menu import (
    build_menu_dialog,
    menu_item,
    close_menu,
)


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
        self.selected_indices: set[int] = set()
        # Shift+click 范围选的锚点索引
        self._anchor_idx: int = -1
        # 双击检测
        self._last_click_idx: int = -1
        self._last_click_ts: float = 0.0
        # 当前打开的右键菜单 (用于关闭)
        self._open_ctx_menu: Optional[ft.AlertDialog] = None
        # 预处理状态变更防抖: 多次快速状态变更合并为一次刷新, 避免连续 page.update 卡 UI
        self._status_refresh_pending: bool = False
        self._status_refresh_scheduled: bool = False

        self._build_ui()

    @property
    def selected_index(self) -> int:
        """向后兼容: 返回最后一个选中的索引, 无选中返回 -1."""
        if self.selected_indices:
            return max(self.selected_indices)
        return -1

    @selected_index.setter
    def selected_index(self, value: int):
        """向后兼容: 设置单个选中."""
        self.selected_indices = {value} if value >= 0 else set()

    def _build_ui(self):
        """构建列表面板 UI"""
        # 列表视图
        self.list_view = ft.ListView(
            expand=True,
            spacing=4,
            padding=ft.Padding(left=12, right=12, top=0, bottom=0),
        )

        # === 常规操作按钮 (仅图标, 鼠标悬停显示文字) ===
        self.btn_add_ext = icon_btn(
            icon=ft.Icons.FOLDER_OPEN,
            tooltip=_("添加外部文件"),
            on_click=self._on_add_external,
        )
        self.btn_insert_above = icon_btn(
            icon=ft.Icons.VERTICAL_ALIGN_TOP,
            tooltip=_("上方插入文本"),
            on_click=self._on_insert_text_above,
            disabled=True,
        )
        self.btn_insert_below = icon_btn(
            icon=ft.Icons.VERTICAL_ALIGN_BOTTOM,
            tooltip=_("下方插入文本"),
            on_click=self._on_insert_text_below,
            disabled=True,
        )
        self.btn_move_up = icon_btn(
            icon=ft.Icons.ARROW_UPWARD,
            tooltip=_("上移"),
            on_click=self._on_move_up,
            disabled=True,
        )
        self.btn_move_down = icon_btn(
            icon=ft.Icons.ARROW_DOWNWARD,
            tooltip=_("下移"),
            on_click=self._on_move_down,
            disabled=True,
        )
        self.btn_ai_toc = icon_btn(
            icon=ft.Icons.SMART_TOY,
            tooltip=_("AI 生成阅读指南"),
            on_click=self._on_ai_toc,
            disabled=True,
        )
        self.btn_delete = icon_btn(
            icon=ft.Icons.DELETE,
            tooltip=_("删除"),
            on_click=self._on_delete,
            disabled=True,
            danger=True,
        )
        self.btn_clear = icon_btn(
            icon=ft.Icons.DELETE_SWEEP,
            tooltip=_("清空"),
            on_click=self._on_clear,
            disabled=True,
            danger=True,
        )

        # 常规操作按钮行
        normal_actions = ft.Row(
            [
                self.btn_add_ext,
                self.btn_insert_above,
                self.btn_insert_below,
                self.btn_move_up,
                self.btn_move_down,
                self.btn_ai_toc,
                self.btn_delete,
                self.btn_clear,
            ],
            spacing=4,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        # === Git 专属操作按钮 (仅图标, 鼠标悬停显示文字) ===
        self.btn_git_add_all_changed = icon_btn(
            icon=ft.Icons.FOLDER_OPEN,
            tooltip=_("一键添加所有改动文件"),
            on_click=self._on_git_add_all_changed,
            disabled=True,
        )
        self.btn_git_export_working_diff = icon_btn(
            icon=ft.Icons.CONTENT_COPY,
            tooltip=_("导出工作区 Diff"),
            on_click=self._on_git_export_working_diff,
            disabled=True,
        )
        self.btn_git_export_commit_diff = icon_btn(
            icon=ft.Icons.SAVE,
            tooltip=_("导出选中 Commit Diff"),
            on_click=self._on_git_export_commit_diff,
            disabled=True,
        )
        self.btn_git_delete = icon_btn(
            icon=ft.Icons.DELETE,
            tooltip=_("删除"),
            on_click=self._on_delete,
            disabled=True,
            danger=True,
        )
        self.btn_git_clear = icon_btn(
            icon=ft.Icons.DELETE_SWEEP,
            tooltip=_("清空"),
            on_click=self._on_clear,
            disabled=True,
            danger=True,
        )

        # Git 操作按钮行
        git_actions = ft.Row(
            [
                self.btn_git_add_all_changed,
                self.btn_git_export_working_diff,
                self.btn_git_export_commit_diff,
                self.btn_git_delete,
                self.btn_git_clear,
            ],
            spacing=4,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        # === 选项区 ===
        # 路径模式
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
            ),
            value="relative" if not self.main_view.engine.use_absolute else "absolute",
            on_change=self._on_path_mode_change,
        )
        self.path_mode_container = ft.Container(content=self.path_mode_group)

        # 头部标注
        self.check_header = ft.Checkbox(
            label=_("在文件头部标注工作目录信息"),
            on_change=self._on_header_change,
            visual_density=ft.VisualDensity.COMPACT,
        )
        self.check_header_container = ft.Container(
            content=ft.Row(
                [self.check_header],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
        )

        # 选项区容器
        options_section = ft.Column(
            [
                self.path_mode_container,
                self.check_header_container,
            ],
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # === 生成按钮 ===
        # Token 进度环: 显示当前编排内容相对上下文窗口的占比
        self.token_ring = ft.ProgressRing(
            value=0,
            width=16,
            height=16,
            stroke_width=2.2,
            color=ft.Colors.GREEN_300,
            bgcolor=ft.Colors.with_opacity(0.35, ft.Colors.WHITE),
            visible=True,
        )
        # 生成合并文本按钮 (带文字标签)
        self.btn_generate_txt = primary_btn(
            text="",
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.SAVE_ALT, size=18, color=ft.Colors.WHITE),
                    ft.Text(_("生成合并文本"), color=ft.Colors.WHITE),
                    self.token_ring,
                ],
                spacing=8,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=PRIMARY,
            on_click=self._on_generate_txt,
            disabled=True,
        )
        # 编排区"更多"菜单 (对齐 gnome generate_menu: 生成到剪贴板 / 导出为 ZIP)
        self.btn_more_menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            tooltip=_("更多操作"),
            disabled=True,
            items=[
                ft.PopupMenuItem(
                    content=ft.Text(_("生成合并文本到剪贴板")),
                    icon=ft.Icons.CONTENT_COPY,
                    on_click=self._on_generate_clipboard,
                ),
                ft.PopupMenuItem(
                    content=ft.Text(_("导出为 ZIP")),
                    icon=ft.Icons.ARCHIVE,
                    on_click=self._on_export_zip,
                ),
            ],
        )

        # 生成按钮行
        generate_row = ft.Row(
            [
                self.btn_generate_txt,
                self.btn_more_menu,
            ],
            spacing=8,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        # === 面板容器结构 ===
        # 编辑操作按钮容器 (Git 模式下隐藏)
        self.edit_actions_column = ft.Column(
            [normal_actions],
            spacing=8,
        )

        # Git 专属操作按钮容器 (默认隐藏)
        self.git_actions_column = ft.Column(
            [git_actions],
            spacing=8,
        )
        self.git_actions_column.visible = False

        # 选项和生成按钮容器 (Git 模式下仍然显示)
        self.export_options_column = ft.Column(
            [options_section, generate_row],
            spacing=8,
        )

        # 面板内容
        panel_content = ft.Column(
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
                        [
                            self.edit_actions_column,
                            self.git_actions_column,
                            self.export_options_column,
                        ],
                        spacing=8,
                    ),
                    padding=ft.Padding(left=12, right=12, bottom=8, top=0),
                ),
            ],
            spacing=0,
            expand=True,
        )

        self.keyboard_listener = ft.KeyboardListener(
            content=panel_content,
            autofocus=True,
            on_key_down=self._on_key_down,
            on_key_up=self._on_key_up,
        )

        # 面板容器
        self.container = ft.Container(
            content=self.keyboard_listener,
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
        self.update_token_display()
        try:
            self.main_view.page.update()
        except Exception:
            pass

    # ============================================================== Token 估算
    def update_token_display(self) -> None:
        """刷新 token 进度环 + 生成按钮 tooltip.

        - text / preprocessed_content: 用 item.cached_tokens
        - 普通文件: 用文件大小 / 3.5 快速估算 (不读内容)
        - header: "# 工作目录绝对路径: ...\\n\\n" 估算
        - 多 item 间分隔符: 每个 +1
        进度环颜色 (已完成弧): <70% 绿, <90% 琥珀, >=90% 红.
        按钮背景始终为蓝色, 不随 ratio 变化.
        """
        import os
        from filecollector.config import get_context_window_size
        from filecollector.token_estimator import estimate_tokens_fast

        engine = self.main_view.engine
        limit = get_context_window_size()
        total = 0

        if engine.show_header and engine.work_dir:
            header = f"# 工作目录绝对路径: {engine.work_dir}\n\n"
            total += estimate_tokens_fast(header)

        for i, data in enumerate(engine.items):
            if i > 0:
                total += 1
            if data.type == "file" and data.path:
                # 显示路径行
                display = self._compute_display_path(data)
                total += estimate_tokens_fast(display + ":\n")
                if data.preprocessed_content:
                    total += data.cached_tokens
                elif data.is_binary_target():
                    # 二进制文件预处理前不估算 token, 只统计转换后的 Markdown
                    pass
                else:
                    total += self._estimate_file_tokens_fast(data.path)
            elif data.type == "text":
                total += data.cached_tokens

        ratio = (total / limit) if limit > 0 else 0.0
        ratio_clamped = max(0.0, min(1.0, ratio))

        if ratio >= 0.9:
            ring_color = ft.Colors.RED_300
        elif ratio >= 0.7:
            ring_color = ft.Colors.AMBER_300
        else:
            ring_color = ft.Colors.GREEN_300

        tooltip = _("预估上下文: %d / %d Tokens (%.1f%%)") % (
            total, limit, ratio * 100,
        )

        try:
            self.token_ring.value = ratio_clamped
            self.token_ring.color = ring_color
            # 轨道色固定为半透明白, 在蓝色按钮上保持可见但不抢眼
            self.token_ring.bgcolor = ft.Colors.with_opacity(
                0.35, ft.Colors.WHITE)
            self.token_ring.tooltip = tooltip
            self.btn_generate_txt.tooltip = tooltip
            self.token_ring.update()
            self.btn_generate_txt.update()
        except Exception:
            pass

    def _compute_display_path(self, data) -> str:
        """计算 item 在导出文本中显示的路径 (与 engine._write_export 一致)."""
        engine = self.main_view.engine
        if not data.path:
            return ""
        return display_path(
            data.path,
            force_absolute=data.force_absolute,
            use_absolute=engine.use_absolute,
            work_dir=engine.work_dir,
        )

    def _estimate_file_tokens_fast(self, path: str) -> int:
        """基于文件大小快速估算 token (>10MB 返回 0)."""
        import os
        try:
            size = os.path.getsize(path)
        except OSError:
            return 0
        if size > 10 * 1024 * 1024:
            return 0
        return int(size / 3.5)

    def _build_list_row(self, idx: int, data: ItemData) -> ft.Container:
        """构建单条列表项 UI."""
        is_selected = idx in self.selected_indices
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
            on_click=lambda e, i=idx: self._on_item_row_click(
                i,
                ctrl_held=bool(getattr(self.main_view, "_ctrl_held", False)),
                shift_held=bool(getattr(self.main_view, "_shift_held", False)),
            ),
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
        count = len(self.selected_indices)
        has_sel = count > 0
        single = count == 1
        has_items = len(self.main_view.engine.items) > 0
        has_work_dir = self.main_view.engine.work_dir is not None

        # 红色按钮禁用时使用浅色图标, 增强视觉对比
        RED_ACTIVE = ft.Colors.RED_600
        RED_DISABLED = ft.Colors.RED_200

        # 常规操作按钮
        self.btn_insert_above.disabled = not single
        self.btn_insert_below.disabled = not single
        self.btn_delete.disabled = not has_sel
        self.btn_delete.icon_color = RED_ACTIVE if has_sel else RED_DISABLED
        self.btn_move_up.disabled = not has_sel or self.selected_index == 0
        self.btn_move_down.disabled = not has_sel or self.selected_index >= len(
            self.main_view.engine.items) - 1
        # 列表为空时, 清空和生成按钮灰显
        for btn in (self.btn_generate_txt, self.btn_more_menu):
            btn.disabled = not has_items
        self.btn_clear.disabled = not has_items
        self.btn_clear.icon_color = RED_ACTIVE if has_items else RED_DISABLED
        # AI 阅读指南需要工作目录 + 列表非空
        self.btn_ai_toc.disabled = not (has_work_dir and has_items)

        # 路径模式 + 头部标注依赖工作目录
        self.path_mode_group.disabled = not has_work_dir
        self.path_mode_container.opacity = 1.0 if has_work_dir else 0.4
        # 头部标注: 绝对路径模式下自动禁用 + 需工作目录
        header_disabled = (not has_work_dir) or self.main_view.engine.use_absolute
        self.check_header.disabled = header_disabled
        self.check_header_container.opacity = 1.0 if not header_disabled else 0.4

        # Git 模式下的删除/清空按钮
        self.btn_git_delete.disabled = not has_sel
        self.btn_git_delete.icon_color = RED_ACTIVE if has_sel else RED_DISABLED
        self.btn_git_clear.disabled = not has_items
        self.btn_git_clear.icon_color = RED_ACTIVE if has_items else RED_DISABLED
        self.btn_git_add_all_changed.disabled = not has_work_dir
        self.btn_git_export_working_diff.disabled = not has_work_dir
        # "导出选中 Commit Diff" 默认禁用, 由 git_history 选中 commit 时启用
        # (对齐 GNOME 版 window.vala:2056, 避免未选中即可点击)
        self.btn_git_export_commit_diff.disabled = True

    def _get_display_text(self, idx: int, data: ItemData) -> str:
        """获取列表项显示文本"""
        if data.type == "file":
            p = Path(data.path)
            if data.is_snippet():
                line_range = _(" [L%d-L%d]") % (data.start_line, data.end_line)
            else:
                line_range = ""
            if data.force_absolute:
                return f"{idx+1}. {p.name}{line_range}  {_('(绝对路径)')}"
            else:
                return f"{idx+1}. {p.name}{line_range}"
        else:
            preview = data.content or ""
            if len(preview) > 30:
                preview = preview[:30] + "..."
            return f"{idx+1}. {preview}"

    def _show_multi_selection_preview(self, count: int) -> None:
        """多选状态时在预览面板显示选中计数."""
        self.main_view.preview_panel.show_raw_text(
            _("已选择 %d 个项目") % count)

    # =============================================================== 鼠标事件
    def _on_item_row_click(self, idx: int, ctrl_held: bool = False,
                           shift_held: bool = False):
        """列表行点击包装: 确保键盘焦点后再走多选逻辑."""
        self._ensure_keyboard_focus()
        self._on_item_click(idx, ctrl_held=ctrl_held, shift_held=shift_held)

    def _on_item_click(self, idx: int, ctrl_held: bool = False,
                       shift_held: bool = False):
        """列表项点击: 检测双击 + Ctrl/Shift 多选.

        - 普通点击: 单选 (清空其他)
        - Ctrl+点击: 切换该条目选中状态 (不动锚点)
        - Shift+点击: 从锚点到该条目范围全选 (锚点未设时退化为单选)
        - 同一条目 300ms 内两次点击: 进入双击编辑
        """
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

        n_items = len(self.main_view.engine.items)
        if shift_held and 0 <= self._anchor_idx < n_items:
            # 范围选: 锚点到当前 idx 之间全部选中
            lo, hi = min(self._anchor_idx, idx), max(self._anchor_idx, idx)
            self.selected_indices = set(range(lo, hi + 1))
        elif ctrl_held:
            # Ctrl+点击: 切换选中状态
            if idx in self.selected_indices:
                self.selected_indices.discard(idx)
            else:
                self.selected_indices.add(idx)
            self._anchor_idx = idx
        else:
            # 普通点击: 单选
            self.selected_indices = {idx}
            self._anchor_idx = idx

        # 更新预览
        indices = sorted(self.selected_indices)
        if len(indices) == 1:
            data = self.main_view.engine.items[indices[0]]
            self.main_view.show_preview(data)
        elif len(indices) > 1:
            self._show_multi_selection_preview(len(indices))
        else:
            self.main_view.clear_preview()
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

    def _on_key_down(self, e: ft.KeyDownEvent):
        """键盘按下: 跟踪 Ctrl / Shift 修饰键."""
        key = e.key.upper()
        if "CONTROL" in key or "CTRL" in key:
            self.main_view._ctrl_held = True
        elif "SHIFT" in key:
            self.main_view._shift_held = True

    def _on_key_up(self, e: ft.KeyUpEvent):
        """键盘释放: 跟踪 Ctrl / Shift 修饰键."""
        key = e.key.upper()
        if "CONTROL" in key or "CTRL" in key:
            self.main_view._ctrl_held = False
        elif "SHIFT" in key:
            self.main_view._shift_held = False

    def _ensure_keyboard_focus(self):
        """确保 KeyboardListener 持有焦点, 以便持续接收按键事件."""
        try:
            self.main_view.page.run_task(self.keyboard_listener.focus())
        except Exception:
            pass

    def _on_item_hover(self, e: ft.HoverEvent, idx: int):
        """列表项悬停"""
        pass

    def _on_item_right_click(self, idx: int, e):
        """鼠标右键 - 弹出操作菜单."""
        self._ensure_keyboard_focus()
        if not (0 <= idx < len(self.main_view.engine.items)):
            return
        # 如果右键的项目不在选中范围内, 则单独选中它
        if idx not in self.selected_indices:
            self.selected_indices = {idx}
            self._anchor_idx = idx
        # 同步显示选中态
        self.refresh()
        data = self.main_view.engine.items[idx]
        self._show_context_menu(idx, data)

    # =============================================================== 右键菜单
    def _show_context_menu(self, idx: int, data: ItemData) -> None:
        """弹出右键菜单 (使用 AlertDialog)."""
        # 关闭已存在的菜单
        if self._open_ctx_menu is not None:
            try:
                self.main_view.page.pop_dialog()
            except Exception:
                pass
            self._open_ctx_menu = None

        count = len(self.selected_indices)
        single = (count == 1)

        # 构建菜单项
        items: list[ft.Control] = []

        # 标题
        if count > 1:
            title = _("已选择 %d 个项目") % count
        elif data.type == "file" and data.path:
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

        # 仅单选时显示的操作
        if single:
            is_binary = (data.type == "file"
                         and data.is_allowed_binary_target(allowed))
            # 编辑文字
            if data.type == "text":
                items.append(menu_item(
                    icon=ft.Icons.EDIT,
                    text=_("编辑文本"),
                    on_click=lambda e, i=idx: (
                        close_menu(self.main_view.page),
                        self._on_edit_text(i),
                    ),
                ))
            # 重新进行 AI 转换
            if is_binary:
                items.append(menu_item(
                    icon=ft.Icons.REFRESH,
                    text=_("重新进行 AI 转换"),
                    on_click=lambda e, i=idx: (
                        close_menu(self.main_view.page),
                        self._on_retry_ai(i),
                    ),
                ))
            # 上方/下方插入文本
            items.append(menu_item(
                icon=ft.Icons.ARROW_UPWARD,
                text=_("在上方插入文本"),
                on_click=lambda e, i=idx: (
                    close_menu(self.main_view.page),
                    self._on_insert_above(i),
                ),
            ))
            items.append(menu_item(
                icon=ft.Icons.ARROW_DOWNWARD,
                text=_("在下方插入文本"),
                on_click=lambda e, i=idx: (
                    close_menu(self.main_view.page),
                    self._on_insert_below(i),
                ),
            ))
            # 上移 / 下移
            items.append(menu_item(
                icon=ft.Icons.ARROW_UPWARD,
                text=_("上移"),
                on_click=lambda e, i=idx: (
                    close_menu(self.main_view.page),
                    self._on_move_up_at(i),
                ),
            ))
            items.append(menu_item(
                icon=ft.Icons.ARROW_DOWNWARD,
                text=_("下移"),
                on_click=lambda e, i=idx: (
                    close_menu(self.main_view.page),
                    self._on_move_down_at(i),
                ),
            ))
            # 复制路径
            if data.type == "file" and data.path:
                items.append(menu_item(
                    icon=ft.Icons.CONTENT_COPY,
                    text=_("复制路径"),
                    on_click=lambda e, p=data.path: (
                        close_menu(self.main_view.page),
                        self._on_copy_path(p),
                    ),
                ))
            # 在文件管理器中显示
            if data.type == "file" and data.path:
                items.append(menu_item(
                    icon=ft.Icons.FOLDER_OPEN,
                    text=_("在文件管理器中显示"),
                    on_click=lambda e, p=data.path: (
                        close_menu(self.main_view.page),
                        self._on_show_in_folder(p),
                    ),
                ))

        # 多选时: 批量重试 AI 转换
        if count > 1:
            can_retry_all = all(
                0 <= i < len(self.main_view.engine.items)
                and self.main_view.engine.items[i].type == "file"
                and self.main_view.engine.items[i].is_allowed_binary_target(allowed)
                and self.main_view.engine.items[i].preprocess_status != PreprocessStatus.PROCESSING
                for i in self.selected_indices
            )
            if can_retry_all:
                items.append(menu_item(
                    icon=ft.Icons.REFRESH,
                    text=_("重新进行 AI 转换 (%d 项)") % count,
                    on_click=lambda e: (
                        close_menu(self.main_view.page),
                        self._on_retry_ai_batch(),
                    ),
                ))

        # 多选时: 批量切换绝对/相对路径 (仅当选中项含外部文件时)
        if count > 1:
            has_external = any(
                0 <= i < len(self.main_view.engine.items)
                and self.main_view.engine.items[i].type == "file"
                and self.main_view.engine.items[i].force_absolute
                for i in self.selected_indices
            )
            if has_external:
                items.append(menu_item(
                    icon=ft.Icons.SWAP_HORIZ,
                    text=_("切换绝对/相对路径 (%d 项)") % count,
                    on_click=lambda e: (
                        close_menu(self.main_view.page),
                        self._on_toggle_absolute_batch(),
                    ),
                ))

        items.append(ft.Divider(height=8, thickness=1))

        # 删除 (支持多选)
        delete_label = (_("删除 (%d 项)") % count
                        if count > 1 else _("删除"))
        items.append(menu_item(
            icon=ft.Icons.DELETE_OUTLINE,
            text=delete_label,
            color=ft.Colors.RED_600,
            on_click=lambda e: (
                close_menu(self.main_view.page),
                self._on_delete_batch(
                    sorted(self.selected_indices, reverse=True)),
            ),
        ))

        dlg = build_menu_dialog(items)
        self._open_ctx_menu = dlg
        try:
            self.main_view.page.show_dialog(dlg)
        except Exception:
            self._open_ctx_menu = None

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
        """强制重新调用 VLM 转换."""
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

    def _on_retry_ai_batch(self):
        """批量重新进行 AI 转换."""
        runner = getattr(self.main_view, "preprocess_runner", None)
        if not runner:
            show_snack(self.main_view.page, _("AI 助手未启用"))
            return
        count = 0
        for idx in self.selected_indices:
            if 0 <= idx < len(self.main_view.engine.items):
                item = self.main_view.engine.items[idx]
                if item.type == "file":
                    runner.retry(item)
                    count += 1
        show_snack(self.main_view.page,
                   _("已重新触发 %d 个文件的 AI 转换") % count)

    def _on_toggle_absolute_batch(self):
        """批量切换绝对/相对路径."""
        self.main_view._push_undo()
        count = 0
        for idx in self.selected_indices:
            if 0 <= idx < len(self.main_view.engine.items):
                item = self.main_view.engine.items[idx]
                if item.type == "file":
                    item.force_absolute = not item.force_absolute
                    count += 1
        self.refresh()
        show_snack(self.main_view.page,
                   _("已切换 %d 个文件的路径模式") % count)

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
            self.selected_indices.discard(idx)
            self.main_view.file_tree_panel.refresh()
            self.refresh()
            show_snack(self.main_view.page, _("条目已删除"))

    def _on_delete_batch(self, indices: list[int]) -> None:
        """批量删除 (indices 应为降序)."""
        if not indices:
            return
        self.main_view._push_undo()
        for idx in indices:
            if 0 <= idx < len(self.main_view.engine.items):
                data = self.main_view.engine.items[idx]
                if data.type == "file" and not data.force_absolute:
                    if data.path in self.main_view.engine.checked_paths:
                        self.main_view.engine.checked_paths.discard(data.path)
                        self.main_view.file_tree_panel.checked_paths.discard(
                            data.path)
                self.main_view.engine.remove_item(idx)
        self.selected_indices.clear()
        self._anchor_idx = -1
        self.main_view.file_tree_panel.refresh()
        self.refresh()
        show_snack(self.main_view.page, _("已删除 %d 个条目") % len(indices))

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
        """删除 (支持多选)"""
        if not self.selected_indices:
            return
        self._on_delete_batch(sorted(self.selected_indices, reverse=True))

    def _on_clear(self, e):
        """清空列表 (带确认 + 项目计数)."""
        if not self.main_view.engine.items:
            return

        def on_confirm(e):
            if e.control.data == "yes":
                self.main_view._push_undo()
                self.main_view.engine.clear()
                self.main_view.file_tree_panel.checked_paths = set(
                    self.main_view.engine.checked_paths
                )
                self.selected_indices.clear()
                self._anchor_idx = -1
                self.refresh()
                self.main_view.file_tree_panel.refresh()
                self._after_items_changed()
                show_snack(self.main_view.page, _("编排列表已清空"))
            self.main_view.page.pop_dialog()

        count = len(self.main_view.engine.items)
        dlg = ft.AlertDialog(
            title=ft.Text(_("确认清空")),
            content=ft.Text(
                _("确定要清空编排列表中的所有 %d 个项目吗？") % count),
            actions=[
                secondary_btn(_("取消"), on_click=on_confirm, data="no"),
                danger_text_btn(
                    _("清空"),
                    on_click=on_confirm,
                    data="yes",
                ),
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
        self.update_token_display()

    def _on_generate_txt(self, e):
        """生成合并文本 (支持 txt/md/json/jsonl/ipynb 多格式导出)."""
        if not self.main_view.engine.items:
            show_snack(self.main_view.page, _("编排列表为空，无法生成。"))
            return

        import datetime

        async def pick():
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            default_name = f"filecollector-export-{stamp}"
            path = await self.main_view._file_picker.save_file(
                dialog_title=_("导出合并文本"),
                file_name=default_name,
                file_type=ft.FilePickerFileType.ANY,
            )
            if not path:
                return
            try:
                fmt_name, saved_path = self._export_by_extension(path)
                show_snack(self.main_view.page, _("%s 已保存") % fmt_name)
                self.main_view.open_file_location(saved_path)
            except Exception as ex:
                show_snack(self.main_view.page, _("生成失败: %s") % ex)

        self.main_view.page.run_task(pick)

    def _export_by_extension(self, path: str) -> tuple[str, str]:
        """根据扩展名分发到对应导出器.

        返回 (格式名, 实际保存路径) — 实际路径可能因补 .txt 后缀而变化.
        """
        from filecollector.multi_format_exporter import (
            export_markdown, export_json, export_jsonl, export_ipynb,
        )
        from filecollector.i18n import _
        from filecollector.utils import display_path

        engine = self.main_view.engine
        work_dir = str(engine.work_dir) if engine.work_dir else None
        lower = path.lower()

        if lower.endswith(".md"):
            export_markdown(path, engine.items, engine.use_absolute,
                            engine.show_header, work_dir)
            return _("Markdown"), path
        if lower.endswith(".jsonl"):
            export_jsonl(path, engine.items, engine.use_absolute,
                         engine.show_header, work_dir)
            return _("JSONL"), path
        if lower.endswith(".json"):
            export_json(path, engine.items, engine.use_absolute,
                        engine.show_header, work_dir)
            return _("JSON"), path
        if lower.endswith(".ipynb"):
            export_ipynb(path, engine.items, engine.use_absolute,
                         engine.show_header, work_dir)
            return _("Jupyter Notebook"), path
        if lower.endswith(".zip"):
            from filecollector.zip_exporter import export_to_zip
            missing, total = export_to_zip(
                path, engine.items, engine.show_header, work_dir,
            )
            if missing:
                show_snack(
                    self.main_view.page,
                    _("已导出 ZIP，%d 个文件在导出时不存在已被跳过") % len(missing),
                )
            return _("ZIP 压缩包"), path
        # 默认 txt
        if not lower.endswith(".txt"):
            path += ".txt"
        engine.export(path)
        return _("合并文本"), path

    def _on_generate_clipboard(self, e):
        """生成到剪贴板 (直接生成字符串, 不创建临时文件)."""
        if not self.main_view.engine.items:
            show_snack(self.main_view.page, _("编排列表为空，无法生成。"))
            return

        try:
            content = self.main_view.engine.generate_text()
            self.main_view.page.set_clipboard(content)
            show_snack(self.main_view.page, _("合并文本已复制到剪贴板"))
        except Exception as ex:
            show_snack(self.main_view.page, _("复制到剪贴板失败: %s") % ex)

    def _on_export_zip(self, e):
        """导出为 ZIP 压缩包 (对齐 gnome generate_menu 的 export_zip)."""
        if not self.main_view.engine.items:
            show_snack(self.main_view.page, _("编排列表为空，无法生成。"))
            return

        import datetime

        async def pick():
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            default_name = f"filecollector-export-{stamp}.zip"
            path = await self.main_view._file_picker.save_file(
                dialog_title=_("导出为 ZIP"),
                file_name=default_name,
                file_type=ft.FilePickerFileType.ANY,
            )
            if not path:
                return
            # 确保以 .zip 结尾
            if not path.lower().endswith(".zip"):
                path += ".zip"
            try:
                from filecollector.zip_exporter import export_to_zip
                engine = self.main_view.engine
                work_dir = str(engine.work_dir) if engine.work_dir else None
                missing, _total = export_to_zip(
                    path, engine.items, engine.show_header, work_dir,
                )
                if missing:
                    show_snack(
                        self.main_view.page,
                        _("已导出 ZIP，%d 个文件在导出时不存在已被跳过")
                        % len(missing),
                    )
                else:
                    show_snack(self.main_view.page, _("ZIP 压缩包 已保存"))
                self.main_view.open_file_location(path)
            except Exception as ex:
                show_snack(self.main_view.page, _("生成失败: %s") % ex)

        self.main_view.page.run_task(pick)

    def _on_ai_toc(self, e):
        """AI 生成阅读指南."""
        self.main_view._on_ai_toc()

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
        """由 main_view 调用: 某条目预处理状态变化, 局部刷新对应行.

        使用防抖机制: 多次快速状态变更 (如 CHECKING -> PROCESSING -> COMPLETED)
        合并为一次刷新, 避免连续 page.update() 卡住 UI 事件循环.

        用 threading.Timer 而非 page.run_task — run_task 在 UI 线程同步代码中
        调用会死锁.
        """
        self._status_refresh_pending = True
        if self._status_refresh_scheduled:
            return
        self._status_refresh_scheduled = True

        def _fire():
            try:
                if self._status_refresh_pending:
                    self._status_refresh_pending = False
                    self.refresh()
            except Exception:
                pass
            finally:
                self._status_refresh_scheduled = False

        import threading
        t = threading.Timer(0.15, _fire)
        t.daemon = True
        t.start()

    # =============================================================== Git 模式切换
    def set_git_mode(self, enabled: bool):
        """切换编辑按钮 / Git 按钮的可见性 (导出选项保持不变)."""
        self.edit_actions_column.visible = not enabled
        self.git_actions_column.visible = enabled
        if not enabled:
            self.btn_git_export_commit_diff.disabled = True
        else:
            self._update_button_states()
        try:
            self.main_view.page.update()
        except Exception:
            pass

    def set_git_export_enabled(self, enabled: bool):
        """启用/禁用 '导出选中 Commit Diff' 按钮."""
        self.btn_git_export_commit_diff.disabled = not enabled
        try:
            self.main_view.page.update()
        except Exception:
            pass

    # =============================================================== Git 按钮事件
    def _on_git_add_all_changed(self, e):
        """一键添加所有改动文件."""
        self.main_view.on_git_add_all_changed(e)

    def _on_git_export_working_diff(self, e):
        """导出工作区 Diff."""
        self.main_view.on_git_export_working_diff(e)

    def _on_git_export_commit_diff(self, e):
        """导出选中 Commit Diff."""
        self.main_view.on_git_export_commit_diff(e)
