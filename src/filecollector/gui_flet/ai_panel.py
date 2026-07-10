"""AI 助手面板.

Flet 版本 - 对话循环和工具调用流程:
- 通过 ``AIClient`` (urllib 同步) 调用 OpenAI 兼容 API
- 在后台线程跑 chat 请求, 通过 ``page.run_task`` 把结果安全地送回 UI
- 工具调用走 ``main_view._execute_ai_tool`` (与 CLI / IPC 共用一套 mutation)
- system prompt 由 ``main_view._ai_state_snapshot`` 提供
"""

from __future__ import annotations

import json
import threading
from typing import Optional

import flet as ft

from filecollector.i18n import _
from filecollector.ai_client import (
    AIClient, AIClientError, TOOL_SCHEMA, build_system_prompt,
)
from filecollector.config import load_templates
from filecollector.gui_flet.ai_settings_dialog import load_ai_settings
from filecollector.gui_flet.buttons import (
    primary_btn, secondary_btn, danger_btn, danger_text_btn, icon_btn,
)


def _uniform_border(width: float = 1, color: str = None) -> ft.border.Border:
    """创建四边统一的边框 (Flet 0.85.3 无 ft.border.all)."""
    side = ft.border.BorderSide(width, color)
    return ft.border.Border(top=side, right=side, bottom=side, left=side)


class AIPanel:
    """AI 助手侧边面板"""

    def __init__(self, main_view):
        self.main_view = main_view

        # 会话状态
        self._client: Optional[AIClient] = None
        self._ai_settings: dict = {}
        self._system_prompt_override: str = ""
        self._messages: list[dict] = []      # OpenAI 风格历史
        self._rendered: list[dict] = []       # 渲染层消息
        self._busy: bool = False
        self._stop_requested: bool = False
        self._tool_counter: int = 0
        self._pending_welcome: bool = True
        self._current_worker: Optional[threading.Thread] = None
        self._resize_timer: Optional[threading.Timer] = None
        # 会话代际: 每次清空对话自增, 后台 API / 工具结果回到主线程时
        # 用于识别旧轮次, 避免把孤立消息加到已清空的列表里.
        self._session_generation: int = 0
        # 模板触发回调: (header_text, footer_text) -> None
        self.template_triggered = None

        self._build_ui()
        self.configure(load_ai_settings())

    # ------------------------------------------------------------------ 配置
    def configure(self, ai_settings: dict) -> None:
        """由 main_view / 设置变更时调用."""
        self._ai_settings = dict(ai_settings)
        self._system_prompt_override = (ai_settings.get(
            "system_prompt_override") or "").strip()

        base = (ai_settings.get("base_url") or "").strip()
        key = (ai_settings.get("api_key") or "").strip()
        model = (ai_settings.get("model") or "").strip()
        timeout = float(ai_settings.get("timeout", 60.0) or 60.0)

        if base and key and model:
            self._client = AIClient(base, key, model, timeout)
        else:
            self._client = None

        self._update_status()

        enabled = bool(ai_settings.get("enabled"))
        if enabled and self._pending_welcome:
            self._pending_welcome = False
            self._render_assistant(
                _("你好, 我是 AI 编排助手。告诉我你想收集哪些文件, 我来帮你编排。\n"
                  "例如: \"把 src 目录下所有 Python 文件加进去, "
                  "然后在开头插入一段任务说明。\"")
            )
        elif not enabled:
            # 禁用时重置标记, 下次启用时重新显示欢迎语
            self._pending_welcome = True

    # ------------------------------------------------------------------ UI 构建
    def _build_ui(self):
        # 状态标签
        self.status_label = ft.Text(
            _("未配置"),
            size=12,
            color=ft.Colors.GREY_600,
        )
        self.model_label = ft.Text(
            "",
            size=12,
            color=ft.Colors.GREY_600,
        )

        # 聊天消息列表
        self.chat_list = ft.ListView(
            expand=True,
            spacing=8,
            padding=ft.Padding(left=12, right=12, top=0, bottom=12),
            auto_scroll=True,
            on_scroll=self._on_chat_scroll,
        )

        # 回到底部按钮 (配色/图标与下方发送按钮同款: 蓝底白图标)
        self.scroll_to_bottom_btn = primary_btn(
            text="",
            content=ft.Icon(ft.Icons.ARROW_DOWNWARD, color=ft.Colors.WHITE),
            on_click=self._scroll_to_bottom,
            visible=False,
            tooltip=_("回到底部"),
        )

        # 输入框
        self.input_field = ft.TextField(
            hint_text=_("输入指令, Enter 发送, Shift+Enter 换行"),
            multiline=True,
            min_lines=1,
            max_lines=3,
            border_radius=8,
            content_padding=ft.Padding(
                left=12, top=8, right=12, bottom=8),
            text_size=14,
            on_submit=self._on_send,
            on_change=self._on_input_changed,
            shift_enter=True,
            expand=True,
        )

        # 补全列表 (默认隐藏, 出现在输入框上方)
        self._completion_list = ft.ListView(
            spacing=0,
            padding=ft.Padding(left=4, top=4, right=4, bottom=4),
            height=0,
        )
        self._completion_container = ft.Container(
            content=self._completion_list,
            border_radius=8,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            border=_uniform_border(1, ft.Colors.OUTLINE_VARIANT),
            visible=False,
        )

        # 发送 / 停止按钮容器 (Flet 0.85 中直接修改 ElevatedButton.text 有时
        # 不会触发客户端刷新, 因此把按钮放在 Row 里, busy 状态变化时重建)
        self.send_btn_row = ft.Row(
            [self._make_send_btn(busy=False)],
            alignment=ft.MainAxisAlignment.END,
        )
        self.clear_btn = secondary_btn(
            _("清空对话"),
            icon=ft.Icons.DELETE_SWEEP,
            on_click=self._on_clear_chat,
        )

        # 面板容器
        self.container = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(
                                    _("AI 助手"),
                                    weight=ft.FontWeight.BOLD,
                                    size=16,
                                    expand=True,
                                ),
                                self.status_label,
                                self.model_label,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.Padding(
                            top=10, bottom=10, left=12, right=12),
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Container(
                        content=ft.Stack(
                            [
                                self.chat_list,
                                ft.Container(
                                    content=self.scroll_to_bottom_btn,
                                    alignment=ft.alignment.Alignment(0, 1),
                                    bottom=16,
                                ),
                            ],
                            expand=True,
                        ),
                        expand=True,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                self._completion_container,
                                self.input_field,
                                ft.Row(
                                    [self.clear_btn,
                                     ft.Container(expand=True),
                                     self.send_btn_row],
                                    spacing=8,
                                ),
                            ],
                            spacing=6,
                        ),
                        padding=ft.Padding(
                            left=12, right=12, bottom=8, top=0),
                    ),
                ],
                spacing=0,
                expand=True,
            ),
            expand=1,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border_radius=12,
            padding=0,
        )

    # ------------------------------------------------------------------ 消息渲染
    def _render_user(self, text: str, undo_token: int = -1) -> None:
        self._rendered.append({
            "type": "user", "content": text, "undo_token": undo_token,
        })
        self._append_user_bubble(text, undo_token)

    def _render_assistant(self, text: str) -> None:
        self._rendered.append({"type": "assistant", "content": text})
        self._append_bubble("assistant", text)

    def _render_system(self, text: str) -> None:
        self._rendered.append({"type": "system", "content": text})
        self._append_bubble("system", text)

    def _render_tool(self, name: str, args: dict, result: str) -> None:
        self._tool_counter += 1
        self._rendered.append({
            "type": "tool",
            "id": self._tool_counter,
            "name": name,
            "args": args,
            "result": result or "OK",
        })
        self._append_tool_bubble(name, args, result or "OK")

    @staticmethod
    def _bubble_width(content: str, max_width: int = 300) -> int:
        """根据内容估算气泡宽度，短内容自适应，长内容不超过最大值."""
        if "\n" in content:
            return max_width
        width = 24  # 左右 padding
        for ch in content:
            width += 16 if ord(ch) > 127 else 8
        return max(60, min(width, max_width))

    @staticmethod
    def _is_short_single_line(content: str, max_width: int = 300) -> bool:
        """判断内容是否为可自适应宽度的短单行内容."""
        if "\n" in content:
            return False
        width = 24
        for ch in content:
            width += 16 if ord(ch) > 127 else 8
        return width < max_width

    def _current_panel_width(self) -> int:
        """估算 AI 面板当前宽度.

        基于窗口宽度估算, 额外预留安全余量以应对:
        - 窗口边框 / 滚动条等占用的像素
        - 估算公式与实际布局的偏差
        窗口变窄时通过 handle_page_resize 触发重绘修正.
        """
        try:
            page_w = self.main_view.page.window.width
            if page_w is None or page_w <= 0:
                return 300
            # 四栏 expand 比例 1:2:1:1，AI 栏占 1/5
            # page_w - 40 = 减去外层左右 padding(16) 与四栏间距(24)
            # 再减 16 安全余量, 避免窗口变窄时气泡被裁切
            return max(200, int((page_w - 40) / 5) - 16)
        except Exception:
            return 300

    def _current_max_bubble_width(self) -> int:
        """根据 AI 面板当前宽度计算气泡最大宽度.
        保留对面方向的固定间距，避免气泡贴边或被裁切.
        """
        # ListView padding 左右各 12，对面方向预留 20 间距
        return max(120, self._current_panel_width() - 12 - 12 - 20)

    def handle_page_resize(self) -> None:
        """窗口尺寸变化时 (由 main_view._on_resize 调用), 防抖重绘气泡.

        估算的气泡宽度可能因窗口尺寸变化而不准, 导致裁切.
        通过防抖重绘所有气泡, 使其适配当前可用宽度.
        """
        if self._resize_timer is not None:
            self._resize_timer.cancel()
        self._resize_timer = threading.Timer(
            0.3, self._rerender_all_async)
        self._resize_timer.daemon = True
        self._resize_timer.start()

    def _rerender_all_async(self) -> None:
        """在 UI 线程中重绘所有已渲染的气泡."""
        page = self.main_view.page
        if page is None:
            return
        page.run_task(self._rerender_all)

    async def _rerender_all(self) -> None:
        """根据当前面板宽度重新创建所有气泡, 修正裁切问题."""
        if not self._rendered:
            return
        self.chat_list.controls.clear()
        for msg in self._rendered:
            mtype = msg.get("type")
            if mtype == "user":
                self._append_user_bubble(
                    msg["content"], msg.get("undo_token", -1))
            elif mtype == "assistant":
                self._append_bubble("assistant", msg["content"])
            elif mtype == "system":
                self._append_bubble("system", msg["content"])
            elif mtype == "tool":
                self._append_tool_bubble(
                    msg["name"], msg["args"], msg["result"])
        if self.main_view.page:
            self.main_view.page.update()

    def _append_bubble(self, role: str, content: str) -> None:
        """添加一个聊天气泡."""
        is_user = role == "user"
        is_system = role == "system"
        max_w = self._current_max_bubble_width()
        short_single_line = self._is_short_single_line(content, max_w)

        msg_key = f"msg_{len(self.chat_list.controls)}"

        def on_link_tap(e):
            url = e.data
            if url and (url.startswith("http://") or url.startswith("https://")):
                self.main_view.page.launch_url(url)

        if is_system:
            bubble_content = ft.Markdown(
                value=content,
                selectable=True,
                extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                code_theme=ft.MarkdownCodeTheme.GITHUB,
                on_tap_link=on_link_tap,
            )
            bubble = ft.Container(
                content=bubble_content,
                padding=ft.Padding(left=12, top=6, right=12, bottom=6),
                border_radius=10,
                bgcolor=ft.Colors.AMBER_50,
                border=_uniform_border(1, ft.Colors.AMBER_200),
                width=None if short_single_line else self._bubble_width(
                    content, max_w),
            )
            row = ft.Row(
                [bubble],
                alignment=ft.MainAxisAlignment.CENTER,
                key=msg_key,
            )
        else:
            if is_user:
                bubble_content = ft.Text(
                    content,
                    size=14,
                    no_wrap=False,
                    color=ft.Colors.WHITE,
                    selectable=True,
                )
                bg_color = ft.Colors.BLUE_600
            else:
                bubble_content = ft.Markdown(
                    value=content,
                    selectable=True,
                    extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                    code_theme=ft.MarkdownCodeTheme.ATOM_ONE_LIGHT,
                    on_tap_link=on_link_tap,
                )
                bg_color = ft.Colors.SURFACE_CONTAINER_LOW

            bubble = ft.Container(
                content=bubble_content,
                padding=12,
                border_radius=12,
                bgcolor=bg_color,
                width=None if short_single_line else self._bubble_width(
                    content, max_w),
            )

            if is_user:
                row = ft.Row(
                    [ft.Container(expand=True), bubble],
                    alignment=ft.MainAxisAlignment.START,
                    key=msg_key,
                )
            else:
                row = ft.Row(
                    [bubble, ft.Container(expand=True)],
                    alignment=ft.MainAxisAlignment.START,
                    key=msg_key,
                )

        self.chat_list.controls.append(row)

    def _append_user_bubble(self, text: str, undo_token: int = -1) -> None:
        """添加用户消息气泡 (带撤回按钮)."""
        max_w = self._current_max_bubble_width()
        short_single_line = self._is_short_single_line(text, max_w)
        msg_key = f"msg_{len(self.chat_list.controls)}"

        bubble_content = ft.Text(
            text,
            size=14,
            no_wrap=False,
            color=ft.Colors.WHITE,
            selectable=True,
            expand=True,
        )

        # 撤回按钮 (仅当 undo_token 有效时显示)
        revert_controls = []
        if undo_token >= 0:
            revert_btn = icon_btn(
                icon=ft.Icons.UNDO,
                tooltip=_("撤回此消息及后续所有 AI 回复与操作"),
                icon_color=ft.Colors.WHITE70,
                on_click=lambda e, t=undo_token, txt=text: self._on_revert_requested(
                    t, txt),
            )
            revert_controls.append(revert_btn)

        bubble = ft.Container(
            content=(
                ft.Row(
                    [bubble_content, *revert_controls],
                    alignment=ft.MainAxisAlignment.END,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                if revert_controls
                else bubble_content
            ),
            padding=12,
            border_radius=12,
            bgcolor=ft.Colors.BLUE_600,
            width=None if short_single_line else self._bubble_width(
                text, max_w),
        )

        row = ft.Row(
            [ft.Container(expand=True), bubble],
            alignment=ft.MainAxisAlignment.START,
            key=msg_key,
        )
        self.chat_list.controls.append(row)

    def _on_revert_requested(self, token: int, text: str) -> None:
        """撤回用户消息及后续所有 AI 操作."""
        if token < 0:
            return

        def on_confirm(e):
            self.main_view.page.pop_dialog()
            if e.control.data != "revert":
                return
            # 停止当前任务
            if self._busy:
                self._request_stop()
            # 撤销到 token 位置
            self.main_view._revert_to_undo_token(token)
            # 移除 rendered 中该消息及后续所有
            revert_idx = -1
            for i, msg in enumerate(self._rendered):
                if (msg.get("undo_token") == token
                        and msg.get("type") == "user"):
                    revert_idx = i
                    break
            if revert_idx >= 0:
                del self._rendered[revert_idx:]
                self._messages.clear()
                # 重建 UI
                self.chat_list.controls.clear()
                for msg in self._rendered:
                    mtype = msg.get("type")
                    if mtype == "user":
                        self._append_user_bubble(
                            msg["content"], msg.get("undo_token", -1))
                    elif mtype == "assistant":
                        self._append_bubble("assistant", msg["content"])
                    elif mtype == "system":
                        self._append_bubble("system", msg["content"])
                    elif mtype == "tool":
                        self._append_tool_bubble(
                            msg["name"], msg["args"], msg["result"])
                # 回填输入框
                self.input_field.value = text
                self.input_field.focus()
                self.main_view.page.update()

        dlg = ft.AlertDialog(
            title=ft.Text(_("确认撤回")),
            content=ft.Text(
                _("这将撤销此消息之后 AI 的所有回复以及对文件列表的修改。是否继续？")),
            actions=[
                secondary_btn(_("取消"), on_click=on_confirm, data="cancel"),
                danger_text_btn(
                    _("撤回"),
                    on_click=on_confirm,
                    data="revert",
                ),
            ],
        )
        self.main_view.page.show_dialog(dlg)

    def _append_tool_bubble(self, name: str, args: dict, result: str) -> None:
        """添加工具调用卡片 (居中, 可展开/折叠).

        - 折叠态: 标题行显示 工具名 + 参数摘要 + 结果预览
        - 展开态: 显示完整结果
        使用 Container + visible 属性手动实现展开/折叠
        (ExpansionTile 在 ListView 中渲染异常)
        """
        args_repr = self._format_tool_args(name, args)

        # 折叠态预览: 结果前 80 字符
        preview = result or ""
        if len(preview) > 80:
            preview = preview[:80] + "…"

        # 展开态: 完整结果
        result_display = result[:2000] + ("…" if len(result) > 2000 else "")

        # 展开图标 (点击切换)
        toggle_icon = ft.Icon(
            ft.Icons.CHEVRON_RIGHT,
            size=16,
            color=ft.Colors.BROWN_700,
        )

        # 展开态: 完整结果容器 (默认不可见)
        body = ft.Container(
            content=ft.Text(
                result_display,
                size=12,
                color=ft.Colors.ON_SURFACE,
                font_family="monospace",
                selectable=True,
                no_wrap=False,
                expand=True,
            ),
            padding=8,
            border_radius=6,
        )

        # 折叠态预览文本 (默认显示) - 使用 expand 避免撑开
        preview_text = ft.Text(
            preview or "—",
            size=11,
            color=ft.Colors.BROWN_700,
            italic=True,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
            expand=True,
        )

        # 外层容器: 通过 visible 控制展开/折叠 (visible=False 时不占空间)
        # 注意: 必须切换外层容器的 visible, 而非内层 body/preview_text 的 visible,
        # 否则外层容器仍会占位 (或仍不可见), 导致展开后内容消失.
        body_wrapper = ft.Container(
            content=body,
            padding=ft.Padding(left=8, top=0, right=8, bottom=8),
            visible=False,
        )
        preview_wrapper = ft.Container(
            content=preview_text,
            padding=ft.Padding(left=30, top=0, right=8, bottom=6),
            visible=True,
        )

        def _toggle(e):
            """切换展开/折叠状态."""
            is_expanded = body_wrapper.visible
            body_wrapper.visible = not is_expanded
            preview_wrapper.visible = is_expanded
            toggle_icon.icon = (
                ft.Icons.EXPAND_MORE if not is_expanded
                else ft.Icons.CHEVRON_RIGHT
            )
            self.main_view.page.update()

        # 标题行 (可点击切换) - args 文本 expand 填充剩余空间
        header = ft.Row(
            [
                toggle_icon,
                ft.Icon(ft.Icons.BUILD, size=14, color=ft.Colors.BROWN_700),
                ft.Text(
                    name,
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.BROWN_900,
                    no_wrap=True,
                ),
                ft.Text(
                    args_repr,
                    size=11,
                    color=ft.Colors.BROWN_700,
                    expand=True,
                    no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
            ],
            spacing=6,
        )

        # 用 GestureDetector 包裹标题行实现点击
        header_tap = ft.GestureDetector(
            content=ft.Container(
                content=header,
                padding=ft.Padding(left=8, top=6, right=8, bottom=6),
            ),
            on_tap=_toggle,
        )

        # 卡片内容: 标题 + 预览/展开内容
        card_content = ft.Column(
            [
                header_tap,
                preview_wrapper,
                body_wrapper,
            ],
            spacing=0,
            tight=True,
        )

        # 卡片容器 - expand=True 填满 ListView 内容区域,
        # 使黄色背景左右边缘与左气泡左边界、右气泡右边界对齐
        card = ft.Container(
            content=card_content,
            expand=True,
            border_radius=8,
            bgcolor=ft.Colors.AMBER_50,
            border=_uniform_border(1, ft.Colors.AMBER_200),
            padding=0,
        )

        self.chat_list.controls.append(
            ft.Row(
                [card],
                key=f"msg_{len(self.chat_list.controls)}",
            )
        )

    @staticmethod
    def _format_tool_args(name: str, args: dict) -> str:
        """把工具参数格式化为一行简短摘要."""
        if name == "add_files" and isinstance(args.get("paths"), list):
            paths = args["paths"]
            if len(paths) <= 3:
                return ", ".join(f'"{p}"' for p in paths)
            return f"{len(paths)} 个文件"
        if name == "read_file":
            return f'"{args.get("path", "")}"'
        if name == "add_text":
            t = (args.get("text") or "")[:30]
            return f'"{t}…"' if len(args.get("text") or "") > 30 else f'"{t}"'
        if name == "set_work_dir":
            return f'"{args.get("path", "")}"'
        if name == "list_files":
            return f'pattern={args.get("pattern", "*")}'
        if name == "list_items":
            return f'kind={args.get("kind", "all")}'
        # 美化 JSON 输出
        try:
            return json.dumps(args, ensure_ascii=False, indent=2)
        except Exception:
            return json.dumps(args, ensure_ascii=False)

    # ------------------------------------------------------------------ 状态
    def _update_status(self) -> None:
        if self._client is None:
            self.status_label.value = _("未配置")
            self.status_label.color = ft.Colors.RED_600
            self.model_label.value = ""
        else:
            self.status_label.value = _("就绪")
            self.status_label.color = ft.Colors.GREEN_700
            self.model_label.value = self._ai_settings.get("model", "") or ""
        if self.main_view.page:
            self.main_view.page.update()

    def _make_send_btn(self, busy: bool):
        """创建发送/停止按钮."""
        if busy:
            return danger_btn(
                _("停止"),
                icon=ft.Icons.STOP,
                on_click=self._on_send_or_stop,
            )
        return primary_btn(
            _("发送"),
            icon=ft.Icons.SEND,
            on_click=self._on_send_or_stop,
        )

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.status_label.value = _("正在思考...")
            self.input_field.disabled = True
        else:
            self._update_status()
            self.input_field.disabled = False
        # 重建按钮并替换, 确保 Flet 客户端正确刷新文字/图标/颜色
        self.send_btn_row.controls = [self._make_send_btn(busy)]
        if self.main_view.page:
            self.main_view.page.update()

    def _on_chat_scroll(self, e: ft.OnScrollEvent) -> None:
        """根据滚动位置显示或隐藏回到底部按钮."""
        max_extent = getattr(e, "max_scroll_extent", 0) or 0
        should_show = max_extent > 0 and e.pixels < max_extent - 50
        if self.scroll_to_bottom_btn.visible != should_show:
            self.scroll_to_bottom_btn.visible = should_show
            e.control.page.update()

    def _scroll_to_bottom(self, _) -> None:
        """点击回到底部按钮."""
        self.main_view.page.run_task(self._scroll_to_bottom_async)
        self.scroll_to_bottom_btn.visible = False
        self.main_view.page.update()

    async def _scroll_to_bottom_async(self) -> None:
        await self.chat_list.scroll_to(offset=-1, duration=300)

    # ------------------------------------------------------------------ 事件
    def _on_send_or_stop(self, e):
        if self._busy:
            self._request_stop()
        else:
            self._on_send(e)

    def _request_stop(self) -> None:
        self._stop_requested = True
        self.status_label.value = _("已停止")
        # 等待中的线程在拿到结果后会自行退出

    def _on_send(self, e):
        if self._busy:
            return
        text = self.input_field.value.strip()
        if not text:
            return
        if self._client is None:
            self._render_system(
                _("请先在 设置 → AI 设置 中启用并配置 API。"))
            self.main_view.page.update()
            return

        # /t 或 /template 斜杠指令
        if text.startswith(("/template ", "/t ")) or text in ("/template", "/t"):
            self.input_field.value = ""
            self._hide_completion()
            self.main_view.page.update()
            self._execute_template_command(text)
            return

        self.input_field.value = ""
        self.main_view.page.update()

        # 添加到消息历史并启动下一轮
        self._send_user_message(text)

    def _on_clear_chat(self, e):
        self._session_generation += 1
        self._rendered.clear()
        self._messages.clear()
        self._tool_counter = 0
        self._pending_welcome = True
        self.chat_list.controls.clear()
        self._hide_completion()
        # 重新渲染欢迎语 (如果仍启用)
        self.configure(self._ai_settings)
        self.main_view.page.update()

    def _execute_template_command(self, text: str) -> None:
        """执行 /t <id> 或 /template <id> 斜杠指令."""
        parts = text.split(" ", 1)
        template_id = parts[1].strip() if len(parts) > 1 else ""

        templates = load_templates()
        tpl = None
        for t in templates:
            if t.get("id") == template_id:
                tpl = t
                break

        if tpl is None:
            # 显示可用模板列表
            sb = []
            if template_id:
                sb.append(_("未找到模板: %s") % template_id)
            else:
                sb.append(_("请输入模板 ID，例如: /t bug"))
            sb.append("")
            sb.append(_("可用模板:"))
            for t in templates:
                line = f"  /t {t['id']} — {t['name']}"
                desc = t.get("description", "")
                if desc:
                    line += f" ({desc})"
                sb.append(line)
            self._render_system("\n".join(sb))
            self.main_view.page.update()
            return

        # 触发模板: 在编排列表头尾插入占位文本
        if self.template_triggered:
            self.template_triggered(
                tpl.get("header_text", ""),
                tpl.get("footer_text", ""),
            )

        # 发送 AI 提示词
        display_msg = f"[应用模板: {tpl['name']}]\n{tpl['ai_prompt']}"
        self._render_user(display_msg)
        self._send_user_message(tpl["ai_prompt"])

    def _execute_template_by_id(self, template_id: str) -> None:
        """通过 ID 执行模板 (供补全列表调用)."""
        templates = load_templates()
        tpl = None
        for t in templates:
            if t.get("id") == template_id:
                tpl = t
                break
        if tpl is None:
            self._render_system(_("未找到模板: %s") % template_id)
            self.main_view.page.update()
            return
        if self.template_triggered:
            self.template_triggered(
                tpl.get("header_text", ""),
                tpl.get("footer_text", ""),
            )
        display_msg = f"[应用模板: {tpl['name']}]\n{tpl['ai_prompt']}"
        self._render_user(display_msg)
        self._send_user_message(tpl["ai_prompt"])

    # ─── 补全列表 ────────────────────────────────────────────────────
    def _on_input_changed(self, e):
        """输入框内容变化: 检测 /t 前缀并显示补全列表."""
        text = (self.input_field.value or "").strip()
        if text.startswith(("/t", "/template")):
            query = ""
            if text.startswith("/template "):
                query = text[10:].strip()
            elif text.startswith("/t "):
                query = text[3:].strip()
            elif text in ("/t", "/template"):
                query = ""
            else:
                query = text[9:] if text.startswith("/template") else text[2:]
            self._show_completion(query)
        else:
            self._hide_completion()

    def _show_completion(self, query: str) -> None:
        """显示补全列表 (根据 query 过滤模板)."""
        templates = load_templates()
        self._completion_list.controls.clear()
        match_count = 0

        for tpl in templates:
            tid = tpl.get("id", "")
            tname = tpl.get("name", "")
            tdesc = tpl.get("description", "")
            if (not query
                    or query.lower() in tid.lower()
                    or query.lower() in tname.lower()):
                row = ft.Container(
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(tname, size=13,
                                            weight=ft.FontWeight.W_600),
                                    ft.Text(
                                        f"/{tid}  •  {tdesc}",
                                        size=11,
                                        color=ft.Colors.GREY_600,
                                    ),
                                ],
                                spacing=2,
                                tight=True,
                                expand=True,
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.Padding(left=10, top=8, right=10, bottom=8),
                    border_radius=6,
                    on_click=lambda e, t=tid: self._apply_completion(t),
                    ink=True,
                )
                self._completion_list.controls.append(row)
                match_count += 1

        if match_count > 0:
            height = min(match_count * 50, 200)
            self._completion_list.height = height
            self._completion_container.visible = True
        else:
            self._hide_completion()
        if self.main_view.page:
            self.main_view.page.update()

    def _hide_completion(self) -> None:
        self._completion_container.visible = False
        self._completion_list.controls.clear()
        if self.main_view.page:
            self.main_view.page.update()

    def _apply_completion(self, template_id: str) -> None:
        """点击补全项: 清空输入框, 执行模板."""
        self._hide_completion()
        self.input_field.value = ""
        if self.main_view.page:
            self.main_view.page.update()
        self._execute_template_by_id(template_id)

    # ------------------------------------------------------------------ 对话循环
    def _send_user_message(self, text: str) -> None:
        # 获取 undo token (当前撤销栈大小), 用于撤回功能
        token = self.main_view.undo_manager.get_stack_size()
        # 新一轮用户输入: 清除上一次的停止标记, 允许后续工具循环继续
        self._stop_requested = False
        self._rebuild_system_message()
        self._messages.append({"role": "user", "content": text})
        self._render_user(text, token)
        self._next_turn()

    def _rebuild_system_message(self) -> None:
        """根据当前 engine 状态重新生成 system message."""
        self._messages = [m for m in self._messages
                          if m.get("role") != "system"]
        work_dir, items, use_abs, show_header = (
            self.main_view._ai_state_snapshot())
        base_prompt = build_system_prompt(
            work_dir, items, use_abs, show_header)
        if self._system_prompt_override:
            content = (self._system_prompt_override
                       + "\n\n" + base_prompt)
        else:
            content = base_prompt
        self._messages.insert(0, {"role": "system", "content": content})

    def _next_turn(self) -> None:
        """启动后台线程跑一次 chat 请求."""
        if self._client is None:
            return
        self._set_busy(True)

        # 拷贝消息列表 (避免后台线程期间 UI 修改 messages)
        messages_snapshot = list(self._messages)
        client = self._client
        tools = TOOL_SCHEMA
        # 记录启动轮次的代际, 回到 UI 线程时若发现代际被清空动作
        # 推进过, 就把响应当作孤儿丢弃, 不写入 messages / 渲染气泡 /
        # 继续 next_turn.
        generation = self._session_generation

        def worker():
            try:
                data = client.chat(messages_snapshot, tools)
            except AIClientError as e:
                err = str(e)
            except Exception as e:  # noqa: BLE001
                err = f"{e}"
            else:
                err = None
            # 回到 UI 线程 (run_task 第一个参数是协程函数, 后跟 *args)
            self.main_view.page.run_task(
                self._on_api_finished_async,
                data if err is None else None,
                err,
                generation,
            )

        self._current_worker = threading.Thread(
            target=worker, daemon=True)
        self._current_worker.start()

    async def _on_api_finished_async(self, data, err, generation):
        """API 调用结束 (在 UI 线程执行)."""
        # 清空对话会让代际推进; 旧轮次的响应 / 工具结果应整体丢弃.
        if generation != self._session_generation:
            return
        self._set_busy(False)
        if self._stop_requested:
            return
        if err is not None:
            self._render_system(_("调用失败: %s") % err)
            self.main_view.page.update()
            return
        try:
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            content = (msg.get("content") or "").strip()
            tool_calls = msg.get("tool_calls") or []
        except Exception as e:  # noqa: BLE001
            self._render_system(_("响应解析失败: %s") % e)
            self.main_view.page.update()
            return

        # page.update() 可能让出事件循环, 清空对话可能在此时发生.
        # 写入历史前再次校验代际, 避免把旧轮次的 assistant 消息
        # (含 tool_calls) 追加到已清空 / 新建的对话中, 形成幽灵历史.
        if generation != self._session_generation:
            return

        # 写入历史 (即使 content 为空, 也要保留 tool_calls)
        assistant_msg: dict = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        self._messages.append(assistant_msg)

        if content:
            self._render_assistant(content)
            self.main_view.page.update()

        if tool_calls:
            for tc in tool_calls:
                name = ((tc.get("function") or {}).get("name") or "").strip()
                raw_args = ((tc.get("function") or {}).get("arguments")
                            or "") or ""
                tc_id = tc.get("id", "")
                try:
                    args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                # 执行工具前再次校验代际: 清空对话可能在上一轮
                # page.update() 让出事件循环时发生, 此时不应再执行
                # 工具 / 渲染工具卡片, 避免污染新对话.
                if generation != self._session_generation:
                    return
                result_str = self._run_tool(name, args)
                # 工具渲染之后再次检查代际: 清空动作可能在工具执行
                # 期间发生, 后续 _next_turn 不应发起新请求.
                if generation != self._session_generation:
                    return
                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_str,
                })
            # 继续下一轮, 让 LLM 基于工具结果回复.
            # 若用户在工具执行期间请求停止, 不再发起新请求,
            # 避免 _next_turn 重置 _stop_requested 导致停止失效.
            if self._stop_requested:
                return
            self._next_turn()

    def _run_tool(self, name: str, args: dict) -> str:
        """执行一次工具调用并显示卡片."""
        executor = getattr(self.main_view, "_execute_ai_tool", None)
        if executor is None:
            return _("未配置工具执行器")
        try:
            result = executor(name, args)
        except Exception as e:  # noqa: BLE001
            result = _("执行出错: %s") % e
        try:
            self._render_tool(name, args, result or "OK")
            self.main_view.page.update()
        except Exception as e:  # noqa: BLE001
            # 渲染失败不应阻塞对话循环, 但需打印日志便于排查
            print(f"[AIPanel] _render_tool failed: {e}")
        return result or "OK"
