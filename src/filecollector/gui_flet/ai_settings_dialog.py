"""AI 助手设置对话框.

允许用户配置 OpenAI 兼容的 API (Microsoft Foundry 上的 Fast Context 等
特化模型同样适用), 写入 ``settings.json`` 的 ``ai`` 字段.

字段:
- enabled    : 是否启用 AI 助手
- base_url   : API 基础地址 (例如 https://api.openai.com/v1)
- api_key    : API 密钥
- model      : 模型名称 (例如 gpt-4o-mini)
- system_prompt_override : 可选, 自定义 system prompt (留空则使用默认)
- timeout    : 请求超时 (秒)

测试连接: 在后台线程发一次最小化 chat 请求, 走 ``AIClient`` (urllib)。
"""

from __future__ import annotations

import threading

import flet as ft

from filecollector.i18n import _
from filecollector.config import load_settings, save_settings
from filecollector.ai_client import AIClient, AIClientError
from filecollector.gui_flet.snack import show_snack


DEFAULT_SETTINGS = {
    "enabled": False,
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "model": "gpt-4o-mini",
    "system_prompt_override": "",
    "timeout": 60.0,
}


def load_ai_settings() -> dict:
    settings = load_settings()
    ai = dict(DEFAULT_SETTINGS)
    ai.update(settings.get("ai", {}) or {})
    return ai


def save_ai_settings(ai: dict) -> None:
    settings = load_settings()
    settings["ai"] = ai
    save_settings(settings)


class AISettingsDialog(ft.AlertDialog):
    """AI 助手设置对话框"""

    def __init__(self, main_view):
        self.main_view = main_view
        self.current = load_ai_settings()

        # 表单字段
        self.chk_enabled = ft.Checkbox(
            label=_("启用 AI 助手"),
            value=self.current.get("enabled", False),
        )

        self.edit_base_url = ft.TextField(
            label=_("API 基础地址:"),
            value=self.current.get("base_url", ""),
            hint_text="https://api.openai.com/v1",
            expand=True,
        )

        self.edit_api_key = ft.TextField(
            label=_("API 密钥:"),
            value=self.current.get("api_key", ""),
            hint_text="sk-...",
            password=True,
            can_reveal_password=True,
            expand=True,
        )

        self.edit_model = ft.TextField(
            label=_("模型名称:"),
            value=self.current.get("model", ""),
            hint_text="gpt-4o-mini",
            expand=True,
        )

        self.spin_timeout = ft.TextField(
            label=_("请求超时 (秒):"),
            value=str(self.current.get("timeout", 60.0)),
            hint_text="60",
            keyboard_type=ft.KeyboardType.NUMBER,
            expand=True,
        )

        self.edit_prompt = ft.TextField(
            label=_("自定义提示词:"),
            value=self.current.get("system_prompt_override", ""),
            hint_text=_("留空则使用默认系统提示词"),
            multiline=True,
            min_lines=2,
            max_lines=4,
            expand=True,
        )

        # 测试连接按钮和状态
        self.btn_test = ft.ElevatedButton(
            _("测试连接"),
            icon=ft.Icons.NETWORK_CHECK,
            on_click=self._on_test,
        )
        self.lbl_test = ft.Text("", size=12, color=ft.Colors.GREY_600)
        self._test_thread: threading.Thread | None = None

        super().__init__(
            title=ft.Text(_("AI 助手设置")),
            content=ft.Column(
                [
                    ft.Text(
                        _("配置 OpenAI 兼容 API, 即可在右侧 AI 边栏使用自然语言编排文件。\n"
                          "支持 OpenAI、Azure OpenAI、Microsoft Foundry 上的 Fast Context 等特化模型, "
                          "以及任何兼容端点 (例如本地 Ollama)。"),
                        size=13,
                        color=ft.Colors.GREY_600,
                        no_wrap=False,
                    ),
                    ft.Divider(),
                    self.chk_enabled,
                    self.edit_base_url,
                    self.edit_api_key,
                    self.edit_model,
                    self.spin_timeout,
                    self.edit_prompt,
                    ft.Row(
                        [self.btn_test, self.lbl_test],
                        spacing=12,
                        alignment=ft.MainAxisAlignment.START,
                    ),
                ],
                tight=True,
                width=420,
            ),
            actions=[
                ft.TextButton(_("取消"), on_click=self._on_cancel),
                ft.TextButton(_("确定"), on_click=self._on_accept),
            ],
        )

    # ------------------------------------------------------------------ 测试连接
    def _on_test(self, e):
        """后台线程跑一次最小化 chat, 验证 base_url / api_key / model."""
        base = self.edit_base_url.value.strip()
        key = self.edit_api_key.value.strip()
        model = self.edit_model.value.strip()
        if not base or not key or not model:
            self.lbl_test.value = _("✗ 请先填写 API 基础地址、密钥和模型名称。")
            self.lbl_test.color = ft.Colors.RED_400
            self.main_view.page.update()
            return

        try:
            timeout = float(self.spin_timeout.value or 60.0)
        except ValueError:
            timeout = 60.0

        # 锁定按钮, 显示 "正在测试"
        self.btn_test.disabled = True
        self.lbl_test.value = _("正在测试…")
        self.lbl_test.color = ft.Colors.GREY_600
        self.main_view.page.update()

        def worker():
            try:
                client = AIClient(base, key, model, timeout)
                client.chat(
                    messages=[
                        {"role": "system", "content": "ping"},
                        {"role": "user", "content": "hi"},
                    ],
                    tools=None,
                )
                ok = True
                err = ""
            except AIClientError as ex:
                ok = False
                err = str(ex)
            except Exception as ex:  # noqa: BLE001
                ok = False
                err = str(ex)
            # 回到 UI 线程 (run_task 第一个参数是协程函数, 后跟 *args)
            self.main_view.page.run_task(
                self._on_test_finished,
                ok,
                err,
            )

        self._test_thread = threading.Thread(target=worker, daemon=True)
        self._test_thread.start()

    async def _on_test_finished(self, ok: bool, err: str):
        """测试结果回调 (UI 线程)."""
        self.btn_test.disabled = False
        if ok:
            self.lbl_test.value = _("✓ 连接成功")
            self.lbl_test.color = ft.Colors.GREEN_700
        else:
            # 截短过长的错误信息
            msg = err[:200] + ("…" if len(err) > 200 else "")
            self.lbl_test.value = _("✗ 失败: %s") % msg
            self.lbl_test.color = ft.Colors.RED_400
        self.main_view.page.update()

    # ------------------------------------------------------------------ 接受/取消
    def _on_accept(self, e):
        """保存设置, 并通知 AI 面板重新加载配置."""
        cfg = {
            "enabled": self.chk_enabled.value,
            "base_url": self.edit_base_url.value.strip(),
            "api_key": self.edit_api_key.value.strip(),
            "model": self.edit_model.value.strip(),
            "system_prompt_override": self.edit_prompt.value,
            "timeout": float(self.spin_timeout.value or 60.0),
        }
        save_ai_settings(cfg)
        # 通知 AI 面板重新加载客户端
        if getattr(self.main_view, "ai_panel", None) is not None:
            self.main_view.ai_panel.configure(cfg)
        self.main_view.page.pop_dialog()
        show_snack(self.main_view.page, _("AI 设置已保存"))

    def _on_cancel(self, e):
        """取消"""
        self.main_view.page.pop_dialog()
