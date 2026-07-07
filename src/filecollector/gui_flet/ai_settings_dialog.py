"""AI 助手设置对话框.

合并 **侧边栏 AI 助手** 与 **视觉语言大模型 (VLM, 二进制文件预处理)** 配置于一个弹窗,
对齐 GNOME 版 ai_settings_dialog.vala.

布局 (从上到下):
    1. 侧边栏 AI 助手  (启用 / URL / Key / Model / 超时 / 提示词 / 测试)
    2. VLM              (启用 / URL / Key / Model / 超时 / 提示词 / 允许扩展名 / 测试)
    3. 扫描忽略目录
    4. 安全警告
"""

from __future__ import annotations

import threading

import flet as ft

from filecollector.i18n import _
from filecollector.config import (
    load_sidebar_ai_settings, save_sidebar_ai_settings,
    load_multimodal_ai_settings, save_multimodal_ai_settings,
    get_allowed_binary_extensions, save_allowed_binary_extensions,
    parse_allowed_ext_input,
)
from filecollector.models import DEFAULT_ALLOWED_BINARY_EXTS
from filecollector.ai_client import AIClient, AIClientError
from filecollector.multimodal_ai_client import (
    MultimodalAIClient, MultimodalAIClientError,
)
from filecollector.gui_flet.snack import show_snack


def _format_ext_default() -> str:
    return ", ".join(DEFAULT_ALLOWED_BINARY_EXTS)


def _format_ext_list(exts) -> str:
    return ", ".join(exts) if exts else ""


# ====================================================================
# 顶层的"分组卡片"组件
# ====================================================================
class _GroupCard(ft.Container):
    """统一外观的设置分组容器."""

    def __init__(self, title: str, description: str = "",
                 controls: list[ft.Control] | None = None):
        header_row = ft.Column(
            [
                ft.Text(title, weight=ft.FontWeight.BOLD, size=14),
                (
                    ft.Text(description, size=12, color=ft.Colors.GREY_600,
                            no_wrap=False)
                    if description else ft.Container()
                ),
            ],
            spacing=2,
        )
        super().__init__(
            content=ft.Column(
                [header_row, *((controls or []))],
                spacing=10, tight=True,
            ),
            border_radius=8,
            # Flet 0.85.x 没有 ft.border.all, 用 Border 四边同值代替
            border=ft.border.Border(
                top=ft.border.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
                right=ft.border.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
                bottom=ft.border.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
                left=ft.border.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
            ),
            padding=ft.Padding(left=12, top=10, right=12, bottom=12),
        )


def _make_http_check_row(label: str, url_field: ft.TextField,
                         warning_container: ft.Container) -> None:
    """输入 URL 时实时判断 http://, 给红色警告文字."""
    def _check(_):
        v = (url_field.value or "").strip()
        if v.startswith("http://") and not v.startswith("https://"):
            warning_container.visible = True
            warning_container.content = ft.Text(
                f"⚠ {label}: 当前使用 HTTP 明文传输, 建议改用 HTTPS",
                size=11, color=ft.Colors.RED_600,
            )
        else:
            warning_container.visible = False
        try:
            warning_container.update()
        except Exception:
            pass
    url_field.on_change = _check


# ====================================================================
# 完整的设置弹窗
# ====================================================================
class AISettingsDialog(ft.AlertDialog):
    """AI 设置: 侧边栏 + 视觉语言大模型 (VLM) 合并入口."""

    def __init__(self, main_view):
        self.main_view = main_view
        self.sidebar_cfg = load_sidebar_ai_settings()
        self.mm_cfg = load_multimodal_ai_settings()
        self.allowed_exts = get_allowed_binary_extensions()

        # --- 侧边栏 AI 控件 ---
        self.sb_enabled = ft.Checkbox(
            label=_("启用 AI 助手"),
            value=bool(self.sidebar_cfg.get("enabled")),
        )
        self.sb_url = ft.TextField(
            label=_("API 基础地址"),
            value=self.sidebar_cfg.get("base_url", ""),
            hint_text="https://api.openai.com/v1",
            expand=True,
        )
        self.sb_key = ft.TextField(
            label=_("API 密钥"),
            value=self.sidebar_cfg.get("api_key", ""),
            hint_text="sk-...",
            password=True,
            can_reveal_password=True,
            expand=True,
        )
        self.sb_model = ft.TextField(
            label=_("模型名称"),
            value=self.sidebar_cfg.get("model", ""),
            hint_text="gpt-4o-mini",
            expand=True,
        )
        self.sb_timeout = ft.TextField(
            label=_("请求超时 (秒)"),
            value=str(self.sidebar_cfg.get("timeout", 60.0) or 60.0),
            hint_text="60",
            keyboard_type=ft.KeyboardType.NUMBER,
            expand=True,
        )
        self.sb_prompt = ft.TextField(
            label=_("自定义系统提示词 (可选)"),
            value=self.sidebar_cfg.get("system_prompt_override", ""),
            hint_text=_("留空则使用默认系统提示词"),
            multiline=True, min_lines=2, max_lines=4,
            expand=True,
        )
        self.sb_warn = ft.Container(visible=False)
        self.sb_test_btn = ft.ElevatedButton(
            _("测试连接"), icon=ft.Icons.NETWORK_CHECK,
            on_click=self._on_test_sidebar,
        )
        self.sb_test_label = ft.Text("", size=12, color=ft.Colors.GREY_600)
        _make_http_check_row(_("侧边栏"), self.sb_url, self.sb_warn)

        # --- 视觉语言大模型 (VLM) 控件 ---
        self.mm_enabled = ft.Checkbox(
            label=_("启用视觉语言大模型 (VLM)"),
            value=bool(self.mm_cfg.get("enabled")),
        )
        self.mm_url = ft.TextField(
            label=_("API 基础地址"),
            value=self.mm_cfg.get("base_url", ""),
            hint_text="https://api.openai.com/v1",
            expand=True,
        )
        self.mm_key = ft.TextField(
            label=_("API 密钥"),
            value=self.mm_cfg.get("api_key", ""),
            hint_text="sk-...",
            password=True,
            can_reveal_password=True,
            expand=True,
        )
        self.mm_model = ft.TextField(
            label=_("模型名称"),
            value=self.mm_cfg.get("model", ""),
            hint_text="gpt-4o",
            expand=True,
        )
        self.mm_timeout = ft.TextField(
            label=_("请求超时 (秒)"),
            value=str(self.mm_cfg.get("timeout", 120.0) or 120.0),
            hint_text="120",
            keyboard_type=ft.KeyboardType.NUMBER,
            expand=True,
        )
        self.mm_prompt = ft.TextField(
            label=_("自定义系统提示词 (可选)"),
            value=self.mm_cfg.get("system_prompt_override", ""),
            hint_text=_("留空则使用默认系统提示词"),
            multiline=True, min_lines=2, max_lines=4,
            expand=True,
        )
        self.mm_exts = ft.TextField(
            label=_("允许转换的二进制扩展名 (逗号分隔, 如 .pdf, .docx)"),
            value=_format_ext_list(self.allowed_exts),
            hint_text=_("留空则不允许任何文件被自动转换"),
            expand=True,
        )
        self.mm_exts_reset_btn = ft.TextButton(
            _("默认"), icon=ft.Icons.RESTART_ALT,
            tooltip=_("恢复为默认扩展名列表"),
            on_click=self._on_reset_exts,
        )
        self.mm_warn = ft.Container(visible=False)
        self.mm_test_btn = ft.ElevatedButton(
            _("测试连接"), icon=ft.Icons.NETWORK_CHECK,
            on_click=self._on_test_mm,
        )
        self.mm_test_label = ft.Text("", size=12, color=ft.Colors.GREY_600)
        _make_http_check_row(_("VLM"), self.mm_url, self.mm_warn)

        # 扫描忽略目录 (沿用原 SettingsDialog 的字段, 此处仅展示)
        ignored_text = self._load_ignored_dirs_text()
        self.ignored_field = ft.TextField(
            label=_("扫描忽略目录 (逗号分隔)"),
            value=ignored_text,
            hint_text="node_modules, .venv, build, dist",
            expand=True,
        )
        # 安全警告
        self.security_label = ft.Text(
            _("⚠ 配置 API 时请确保使用可信网络与 HTTPS, 避免密钥泄露。"),
            size=12, color=ft.Colors.RED_600,
        )

        # 拼装内容
        sidebar_card = _GroupCard(
            _("AI 助手 (侧边栏)"),
            _("配置 OpenAI 兼容 API, 在 AI 边栏使用自然语言编排文件。"),
            [
                self.sb_enabled,
                self.sb_url, self.sb_warn, self.sb_key, self.sb_model,
                self.sb_timeout, self.sb_prompt,
                ft.Row([self.sb_test_btn, self.sb_test_label],
                       spacing=12, alignment=ft.MainAxisAlignment.START),
            ],
        )

        mm_card = _GroupCard(
            _("视觉语言大模型 (二进制文件预处理)"),
            _("配置视觉语言大模型（VLM）API, 用于将 PDF、Word、PPT、图片等转为 Markdown。"),
            [
                self.mm_enabled,
                self.mm_url, self.mm_warn, self.mm_key, self.mm_model,
                self.mm_timeout, self.mm_prompt,
                ft.Row(
                    [self.mm_exts, self.mm_exts_reset_btn],
                    spacing=4, alignment=ft.MainAxisAlignment.START,
                ),
                ft.Row([self.mm_test_btn, self.mm_test_label],
                       spacing=12, alignment=ft.MainAxisAlignment.START),
            ],
        )

        ignored_card = _GroupCard(
            _("扫描忽略目录"),
            _("这些目录不会出现在文件树中, 也不会被自动收集。"),
            [self.ignored_field],
        )

        security_card = _GroupCard(
            _("安全警告"), "", [self.security_label],
        )

        super().__init__(
            title=ft.Text(_("AI 设置")),
            content=ft.Container(
                content=ft.Column(
                    [sidebar_card, mm_card, ignored_card, security_card],
                    spacing=12, tight=True, scroll=ft.ScrollMode.AUTO,
                ),
                width=520,
            ),
            actions=[
                ft.TextButton(_("取消"), on_click=self._on_cancel),
                ft.TextButton(_("保存"), on_click=self._on_accept),
            ],
        )

        self._test_thread: threading.Thread | None = None

    # ============================================================== 辅助
    def _try_update(self, ctrl: ft.Control) -> None:
        try:
            ctrl.update()
        except Exception:
            pass

    def _on_reset_exts(self, _):
        self.mm_exts.value = _format_ext_default()
        self._try_update(self.mm_exts)

    def _load_ignored_dirs_text(self) -> str:
        try:
            from filecollector.config import load_settings
            cfg = load_settings()
            arr = cfg.get("ignored_dirs", [])
            if isinstance(arr, list):
                return ", ".join(str(x) for x in arr)
        except Exception:
            pass
        return ""

    def _save_ignored_dirs(self, raw: str) -> None:
        from filecollector.config import load_settings, save_settings
        parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
        cfg = load_settings()
        cfg["ignored_dirs"] = parts
        save_settings(cfg)

    # ============================================================== 测试连接
    def _on_test_sidebar(self, e):
        base = (self.sb_url.value or "").strip()
        key = (self.sb_key.value or "").strip()
        model = (self.sb_model.value or "").strip()
        if not base or not key or not model:
            self._set_test_label(self.sb_test_label,
                                 _("✗ 请先填写 API 基础地址、密钥和模型名称。"),
                                 ft.Colors.RED_400)
            return
        try:
            timeout = float(self.sb_timeout.value or 60.0)
        except ValueError:
            timeout = 60.0

        self.sb_test_btn.disabled = True
        self._set_test_label(self.sb_test_label, _("正在测试..."),
                             ft.Colors.GREY_600)
        self._try_update(self.sb_test_btn)

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
                ok, err = True, ""
            except AIClientError as ex:
                ok, err = False, str(ex)
            except Exception as ex:  # noqa: BLE001
                ok, err = False, str(ex)
            self.main_view.page.run_task(
                self._on_test_finished, "sidebar", ok, err,
            )

        self._test_thread = threading.Thread(target=worker, daemon=True)
        self._test_thread.start()

    def _on_test_mm(self, e):
        base = (self.mm_url.value or "").strip()
        key = (self.mm_key.value or "").strip()
        model = (self.mm_model.value or "").strip()
        if not base or not key or not model:
            self._set_test_label(self.mm_test_label,
                                 _("✗ 请先填写 API 基础地址、密钥和模型名称。"),
                                 ft.Colors.RED_400)
            return
        try:
            timeout = float(self.mm_timeout.value or 120.0)
        except ValueError:
            timeout = 120.0

        self.mm_test_btn.disabled = True
        self._set_test_label(self.mm_test_label, _("正在测试..."),
                             ft.Colors.GREY_600)
        self._try_update(self.mm_test_btn)

        def worker():
            try:
                client = MultimodalAIClient(
                    base, key, model,
                    "Reply with a single short word 'pong'.",
                    timeout,
                )
                # 用 1x1 透明 PNG 当作"最小测试图"避免拉取真实文件
                from filecollector.multimodal_ai_client import (
                    encode_file_to_base64,
                )
                # 一个最小的 1x1 透明 PNG
                tiny_png = (
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAY"
                    "AAjCB0C8AAAAASUVORK5CYII="
                )
                client.process_images([tiny_png], ["image/png"])
                ok, err = True, ""
            except MultimodalAIClientError as ex:
                ok, err = False, str(ex)
            except Exception as ex:  # noqa: BLE001
                ok, err = False, str(ex)
            self.main_view.page.run_task(
                self._on_test_finished, "mm", ok, err,
            )

        self._test_thread = threading.Thread(target=worker, daemon=True)
        self._test_thread.start()

    def _set_test_label(self, lbl: ft.Text, text: str, color):
        lbl.value = text
        lbl.color = color
        self._try_update(lbl)

    async def _on_test_finished(self, which: str, ok: bool, err: str):
        if which == "sidebar":
            btn, lbl = self.sb_test_btn, self.sb_test_label
        else:
            btn, lbl = self.mm_test_btn, self.mm_test_label
        btn.disabled = False
        if ok:
            self._set_test_label(lbl, _("✓ 连接成功"), ft.Colors.GREEN_700)
        else:
            msg = err[:200] + ("…" if len(err) > 200 else "")
            self._set_test_label(lbl, _("✗ 失败: %s") % msg, ft.Colors.RED_400)
        self._try_update(btn)

    # ============================================================== 接受 / 取消
    def _on_accept(self, e):
        # 侧边栏
        try:
            sb_timeout = float(self.sb_timeout.value or 60.0)
        except ValueError:
            sb_timeout = 60.0
        sb_cfg = {
            "enabled": bool(self.sb_enabled.value),
            "base_url": (self.sb_url.value or "").strip(),
            "api_key": (self.sb_key.value or "").strip(),
            "model": (self.sb_model.value or "").strip(),
            "system_prompt_override": self.sb_prompt.value or "",
            "timeout": sb_timeout,
        }
        save_sidebar_ai_settings(sb_cfg)

        # VLM
        try:
            mm_timeout = float(self.mm_timeout.value or 120.0)
        except ValueError:
            mm_timeout = 120.0
        mm_cfg = {
            "enabled": bool(self.mm_enabled.value),
            "base_url": (self.mm_url.value or "").strip(),
            "api_key": (self.mm_key.value or "").strip(),
            "model": (self.mm_model.value or "").strip(),
            "system_prompt_override": self.mm_prompt.value or "",
            "timeout": mm_timeout,
        }
        save_multimodal_ai_settings(mm_cfg)

        # 允许的扩展名 (空数组 = 不允许任何文件)
        new_exts = parse_allowed_ext_input(self.mm_exts.value or "")
        save_allowed_binary_extensions(new_exts)

        # 忽略目录
        try:
            self._save_ignored_dirs(self.ignored_field.value or "")
        except Exception:
            pass

        # 通知 AI 面板重载
        if getattr(self.main_view, "ai_panel", None) is not None:
            self.main_view.ai_panel.configure(sb_cfg)

        # 通知 main_view: 扩展名可能变更, 让编排列表重新评估
        if hasattr(self.main_view, "_on_ai_settings_changed"):
            try:
                self.main_view._on_ai_settings_changed()
            except Exception as ex:  # noqa: BLE001
                print(f"[AISettingsDialog] _on_ai_settings_changed failed: {ex}")

        try:
            self.main_view.page.pop_dialog()
        except Exception:
            pass

    def _on_cancel(self, e):
        try:
            self.main_view.page.pop_dialog()
        except Exception:
            pass


# ====================================================================
# 向后兼容: 保留旧函数名 load_ai_settings, 以免老代码 (ai_panel.py) 引用失败
# ====================================================================
def load_ai_settings() -> dict:
    return load_sidebar_ai_settings()
