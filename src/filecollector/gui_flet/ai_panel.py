"""AI 助手面板.

Flet 版本 - 复刻 PySide6 实现的对话循环和工具调用流程:
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
from filecollector.gui_flet.ai_settings_dialog import load_ai_settings


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

        # 回到底部按钮
        self.scroll_to_bottom_btn = ft.ElevatedButton(
            content=ft.Icon(ft.Icons.ARROW_DOWNWARD),
            tooltip=_("回到底部"),
            on_click=self._scroll_to_bottom,
            style=ft.ButtonStyle(
                shape=ft.CircleBorder(),
                padding=ft.Padding(8, 8, 8, 8),
            ),
            visible=False,
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
            shift_enter=True,
            expand=True,
        )

        # 发送 / 停止按钮
        self.send_btn = ft.ElevatedButton(
            _("发送"),
            icon=ft.Icons.SEND,
            on_click=self._on_send_or_stop,
        )
        self.clear_btn = ft.TextButton(
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
                                    right=16,
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
                                self.input_field,
                                ft.Row(
                                    [self.clear_btn,
                                     ft.Container(expand=True),
                                     self.send_btn],
                                    spacing=8,
                                ),
                            ],
                            spacing=6,
                        ),
                        padding=ft.Padding(
                            left=12, right=12, bottom=12, top=0),
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
    def _render_user(self, text: str) -> None:
        self._rendered.append({"type": "user", "content": text})
        self._append_bubble("user", text)

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
                self._append_bubble("user", msg["content"])
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
        if is_system:
            bubble = ft.Container(
                content=ft.Text(
                    content, size=12, color=ft.Colors.ON_SURFACE_VARIANT,
                    text_align=ft.TextAlign.CENTER, no_wrap=False,
                ),
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
            bubble = ft.Container(
                content=ft.Text(
                    content,
                    size=14,
                    no_wrap=False,
                    color=ft.Colors.WHITE if is_user else ft.Colors.ON_SURFACE,
                    selectable=True,
                ),
                padding=12,
                border_radius=12,
                bgcolor=ft.Colors.BLUE_600 if is_user else ft.Colors.SURFACE_CONTAINER_LOW,
                width=None if short_single_line else self._bubble_width(
                    content, max_w),
            )
            if is_user:
                # 靠右气泡：左侧留固定间距
                row = ft.Row(
                    [
                        ft.Container(expand=True),
                        bubble,
                    ],
                    alignment=ft.MainAxisAlignment.START,
                    key=msg_key,
                )
            else:
                # 靠左气泡：右侧留固定间距
                row = ft.Row(
                    [
                        bubble,
                        ft.Container(expand=True),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                    key=msg_key,
                )

        self.chat_list.controls.append(row)

    def _append_tool_bubble(self, name: str, args: dict, result: str) -> None:
        """添加工具调用卡片 (居中, 可展开/折叠, 对齐 Qt 版 _add_tool_bubble).

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

        # 展开内容 (默认隐藏) - Text 使用 expand 填充容器宽度, 避免撑开
        body = ft.Container(
            content=ft.Text(
                result_display,
                size=11,
                color=ft.Colors.ON_SURFACE,
                font_family="monospace",
                selectable=True,
                no_wrap=False,
                expand=True,
            ),
            bgcolor=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
            padding=8,
            border_radius=6,
            visible=False,
        )

        # 折叠态预览文本 (默认显示) - 使用 expand 避免撑开
        preview_text = ft.Text(
            preview or "—",
            size=11,
            color=ft.Colors.BROWN_700,
            italic=True,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
            visible=True,
            expand=True,
        )

        def _toggle(e):
            """切换展开/折叠状态."""
            is_expanded = body.visible
            body.visible = not is_expanded
            preview_text.visible = is_expanded
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
                ft.Container(
                    content=preview_text,
                    padding=ft.Padding(left=30, top=0, right=8, bottom=6),
                    visible=True,
                ),
                ft.Container(
                    content=body,
                    padding=ft.Padding(left=8, top=0, right=8, bottom=8),
                    visible=False,
                ),
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

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.send_btn.text = _("停止")
            self.send_btn.icon = ft.Icons.STOP
            self.send_btn.bgcolor = ft.Colors.RED_600
            self.send_btn.color = ft.Colors.WHITE
            self.status_label.value = _("正在思考...")
            self.input_field.disabled = True
        else:
            self.send_btn.text = _("发送")
            self.send_btn.icon = ft.Icons.SEND
            self.send_btn.bgcolor = None
            self.send_btn.color = None
            self._update_status()
            self.input_field.disabled = False
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
        # 通过临时添加一个不可见控件触发 auto_scroll 滚动到底部
        dummy = ft.Container(height=1, width=1, opacity=0)
        self.chat_list.controls.append(dummy)
        self.main_view.page.update()
        self.chat_list.controls.remove(dummy)
        self.scroll_to_bottom_btn.visible = False
        self.main_view.page.update()

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
        text = self.input_field.value.strip()
        if not text:
            return
        if self._client is None:
            self._render_system(
                _("请先在 设置 → AI 设置 中启用并配置 API。"))
            self.main_view.page.update()
            return

        self._render_user(text)
        self.input_field.value = ""
        self.main_view.page.update()

        # 添加到消息历史并启动下一轮
        self._send_user_message(text)

    def _on_clear_chat(self, e):
        self._rendered.clear()
        self._messages.clear()
        self._tool_counter = 0
        self._pending_welcome = True
        self.chat_list.controls.clear()
        # 重新渲染欢迎语 (如果仍启用)
        self.configure(self._ai_settings)
        self.main_view.page.update()

    # ------------------------------------------------------------------ 对话循环
    def _send_user_message(self, text: str) -> None:
        self._rebuild_system_message()
        self._messages.append({"role": "user", "content": text})
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
        self._stop_requested = False

        # 拷贝消息列表 (避免后台线程期间 UI 修改 messages)
        messages_snapshot = list(self._messages)
        client = self._client
        tools = TOOL_SCHEMA

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
            )

        self._current_worker = threading.Thread(
            target=worker, daemon=True)
        self._current_worker.start()

    async def _on_api_finished_async(self, data, err):
        """API 调用结束 (在 UI 线程执行)."""
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
                result_str = self._run_tool(name, args)
                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_str,
                })
            # 继续下一轮, 让 LLM 基于工具结果回复
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
