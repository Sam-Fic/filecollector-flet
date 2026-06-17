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
            padding=12,
            auto_scroll=True,
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
                            top=12, bottom=8, left=12, right=12),
                    ),
                    ft.Container(
                        content=self.chat_list,
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
            width=360,
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

    def _append_bubble(self, role: str, content: str) -> None:
        """添加一个聊天气泡."""
        is_user = role == "user"
        is_system = role == "system"

        if is_system:
            bubble = ft.Container(
                content=ft.Text(
                    content, size=12, color=ft.Colors.ON_SURFACE_VARIANT,
                    text_align=ft.TextAlign.CENTER, no_wrap=False,
                ),
                padding=ft.Padding(left=12, top=6, right=12, bottom=6),
                border_radius=10,
                bgcolor=ft.Colors.AMBER_50,
                border=ft.border.all(1, ft.Colors.AMBER_200),
                width=300,
            )
            row = ft.Row(
                [bubble],
                alignment=ft.MainAxisAlignment.CENTER,
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
                bgcolor=ft.Colors.BLUE_400 if is_user else ft.Colors.SURFACE_CONTAINER_LOW,
                width=300,
            )
            if is_user:
                row = ft.Row(
                    [bubble],
                    alignment=ft.MainAxisAlignment.END,
                )
            else:
                row = ft.Row(
                    [bubble],
                    alignment=ft.MainAxisAlignment.START,
                )

        self.chat_list.controls.append(row)

    def _append_tool_bubble(self, name: str, args: dict, result: str) -> None:
        """添加工具调用卡片 (展开/折叠)."""
        header = ft.Row(
            [
                ft.Icon(ft.Icons.BUILD, size=14, color=ft.Colors.BROWN_700),
                ft.Text(
                    name,
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.BROWN_900,
                ),
                ft.Text(
                    self._format_tool_args(name, args),
                    size=11,
                    color=ft.Colors.BROWN_700,
                    expand=True,
                    no_wrap=False,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
            ],
            spacing=6,
        )

        # 折叠面板 - 包含 args JSON 和 result
        body = ft.Column(
            [
                ft.Container(
                    content=ft.Text(
                        json.dumps(args, ensure_ascii=False, indent=2),
                        size=11,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        font_family="monospace",
                        selectable=True,
                    ),
                    bgcolor=ft.Colors.with_opacity(0.5, ft.Colors.BLACK),
                    padding=8,
                    border_radius=6,
                ),
                ft.Text(_("结果:"), size=11, color=ft.Colors.BROWN_700),
                ft.Container(
                    content=ft.Text(
                        result[:1000] + ("…" if len(result) > 1000 else ""),
                        size=11,
                        color=ft.Colors.ON_SURFACE,
                        font_family="monospace",
                        selectable=True,
                        no_wrap=False,
                    ),
                    bgcolor=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
                    padding=8,
                    border_radius=6,
                ),
            ],
            spacing=4,
        )

        exp = ft.ExpansionTile(
            title=header,
            controls=[ft.Container(content=body, padding=8)],
            tile_padding=ft.Padding(
                left=4, top=0, right=4, bottom=0),
            initially_expanded=False,
        )

        card = ft.Container(
            content=exp,
            padding=ft.Padding(left=4, right=4, top=0, bottom=0),
            border_radius=8,
            bgcolor=ft.Colors.AMBER_50,
            border=ft.border.all(1, ft.Colors.AMBER_200),
        )
        self.chat_list.controls.append(
            ft.Row([card], alignment=ft.MainAxisAlignment.START)
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
            self.status_label.color = ft.Colors.RED_400
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
            self.send_btn.bgcolor = ft.Colors.RED_400
            self.status_label.value = _("正在思考…")
            self.input_field.disabled = True
        else:
            self.send_btn.text = _("发送")
            self.send_btn.icon = ft.Icons.SEND
            self.send_btn.bgcolor = None
            self._update_status()
            self.input_field.disabled = False
        if self.main_view.page:
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


Gdk-Message: 22: 00: 09.072: Unable to load from the cursor theme
embedder.cc(2575): 'FlutterEngineRemoveView' returned 'kInvalidArguments'. Re
move view info was invalid. The implicit view cannot be removed.
** (flet: 127892): WARNING **: 22: 01: 01.350: Failed to cleanup compositor shade
rs, unable to make OpenGL context current
** (flet: 127892): WARNING **: 22: 01: 01.355: Attempted to set message handler o
n an FlBinaryMessenger without an engine
** (flet: 127892): WARNING **: 22: 01: 01.355: Attempted to set message handler o
n an FlBinaryMessenger without an engine

选择文件夹后，卡在加载不动了                err = None
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
        except Exception:
            pass
        return result or "OK"
