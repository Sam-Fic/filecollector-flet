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
"""

from __future__ import annotations

import json
import urllib.error

from PySide6.QtCore import Qt, QThread, QObject, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QFrame,
    QLineEdit, QCheckBox, QPushButton, QLabel, QDoubleSpinBox,
    QDialogButtonBox, QMessageBox,
)

from filecollector.i18n import _
from filecollector.config import load_settings, save_settings, BUTTON_HEIGHT
from filecollector.ai_client import AIClient, AIClientError


DEFAULT_SETTINGS: dict = {
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


class _TestWorker(QObject):
    """在后台线程发起一次最小化 chat 请求, 验证 API 配置可用."""

    finished = Signal(bool, str)

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float):
        super().__init__()
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def run(self) -> None:
        client = AIClient(self._base_url, self._api_key, self._model, self._timeout)
        try:
            client.chat(
                messages=[
                    {"role": "system", "content": "ping"},
                    {"role": "user", "content": "hi"},
                ],
                tools=None,
            )
        except AIClientError as e:
            self.finished.emit(False, str(e))
        except Exception as e:  # noqa: BLE001
            self.finished.emit(False, str(e))
        else:
            self.finished.emit(True, "OK")


class AISettingsDialog(QDialog):
    """AI 助手设置面板."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("AI 助手设置"))
        self.setModal(True)
        self.setMinimumWidth(480)

        self._current = load_ai_settings()
        self._build_ui()
        self._load_into_ui()
        self._test_thread: QThread | None = None
        self._test_worker: _TestWorker | None = None

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel(_("AI 助手设置"))
        f = title.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 1)
        title.setFont(f)
        root.addWidget(title)

        desc = QLabel(
            _("配置 OpenAI 兼容 API, 即可在右侧 AI 边栏使用自然语言编排文件。\n"
              "支持 OpenAI、Azure OpenAI、Microsoft Foundry 上的 Fast Context 等特化模型, "
              "以及任何兼容端点 (例如本地 Ollama)。")
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #5e5c64;")
        root.addWidget(desc)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        root.addWidget(line)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)

        self.chk_enabled = QCheckBox(_("启用 AI 助手"))
        form.addRow(self.chk_enabled)

        self.edit_base_url = QLineEdit()
        self.edit_base_url.setPlaceholderText("https://api.openai.com/v1")
        form.addRow(_("API 基础地址:"), self.edit_base_url)

        self.edit_api_key = QLineEdit()
        self.edit_api_key.setEchoMode(QLineEdit.Password)
        self.edit_api_key.setPlaceholderText("sk-...")
        form.addRow(_("API 密钥:"), self.edit_api_key)

        self.edit_model = QLineEdit()
        self.edit_model.setPlaceholderText("gpt-4o-mini")
        form.addRow(_("模型名称:"), self.edit_model)

        self.spin_timeout = QDoubleSpinBox()
        self.spin_timeout.setRange(5.0, 600.0)
        self.spin_timeout.setSingleStep(5.0)
        self.spin_timeout.setSuffix(" s")
        form.addRow(_("请求超时:"), self.spin_timeout)

        self.edit_prompt = QLineEdit()
        self.edit_prompt.setPlaceholderText(_("留空则使用默认系统提示词"))
        form.addRow(_("自定义提示词:"), self.edit_prompt)

        root.addLayout(form)

        # 测试连接
        test_row = QHBoxLayout()
        self.btn_test = QPushButton(_("测试连接"))
        self.btn_test.setFixedHeight(BUTTON_HEIGHT)
        self.btn_test.clicked.connect(self._on_test)
        self.lbl_test = QLabel("")
        self.lbl_test.setStyleSheet("color: #5e5c64;")
        test_row.addWidget(self.btn_test)
        test_row.addWidget(self.lbl_test, 1)
        test_row.addStretch()
        root.addLayout(test_row)

        root.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(_("确定"))
        buttons.button(QDialogButtonBox.Cancel).setText(_("取消"))
        for btn in buttons.buttons():
            btn.setFixedHeight(BUTTON_HEIGHT)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load_into_ui(self) -> None:
        self.chk_enabled.setChecked(bool(self._current.get("enabled")))
        self.edit_base_url.setText(self._current.get("base_url", "") or "")
        self.edit_api_key.setText(self._current.get("api_key", "") or "")
        self.edit_model.setText(self._current.get("model", "") or "")
        self.spin_timeout.setValue(float(self._current.get("timeout", 60.0) or 60.0))
        self.edit_prompt.setText(self._current.get("system_prompt_override", "") or "")

    def _collect_from_ui(self) -> dict:
        return {
            "enabled": self.chk_enabled.isChecked(),
            "base_url": self.edit_base_url.text().strip(),
            "api_key": self.edit_api_key.text().strip(),
            "model": self.edit_model.text().strip(),
            "system_prompt_override": self.edit_prompt.text(),
            "timeout": float(self.spin_timeout.value()),
        }

    # ------------------------------------------------------------------ 行为
    def _on_test(self) -> None:
        cfg = self._collect_from_ui()
        if not cfg["base_url"] or not cfg["api_key"] or not cfg["model"]:
            QMessageBox.warning(self, _("提示"), _("请先填写 API 基础地址、密钥和模型名称。"))
            return
        self.btn_test.setEnabled(False)
        self.lbl_test.setText(_("正在测试..."))
        self.lbl_test.setStyleSheet("color: #5e5c64;")

        self._test_thread = QThread(self)
        self._test_worker = _TestWorker(
            cfg["base_url"], cfg["api_key"], cfg["model"], cfg["timeout"],
        )
        self._test_worker.moveToThread(self._test_thread)
        self._test_thread.started.connect(self._test_worker.run)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_thread.start()

    def _on_test_finished(self, ok: bool, msg: str) -> None:
        self.btn_test.setEnabled(True)
        if self._test_thread is not None:
            self._test_thread.quit()
            self._test_thread.wait()
        self._test_thread = None
        self._test_worker = None
        if ok:
            self.lbl_test.setText(_("✓ 连接成功"))
            self.lbl_test.setStyleSheet("color: #2ec27e;")
        else:
            self.lbl_test.setText(_("✗ 失败: %s") % msg)
            self.lbl_test.setStyleSheet("color: #c01c28;")

    def _on_accept(self) -> None:
        cfg = self._collect_from_ui()
        save_ai_settings(cfg)
        self.accept()
