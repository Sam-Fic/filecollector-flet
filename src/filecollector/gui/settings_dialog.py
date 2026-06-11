"""语言设置对话框.

提供 跟随系统 / 中文 / English 三个互斥选项, 选中后写入配置文件并立即生效.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QButtonGroup, QRadioButton,
    QDialogButtonBox, QLabel, QFrame,
)

from filecollector.i18n import _, get_language, set_language
from filecollector.config import save_settings, load_settings, BUTTON_HEIGHT


class SettingsDialog(QDialog):
    """语言选择对话框."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("设置界面语言"))
        self.setModal(True)
        self.setMinimumWidth(360)

        self._saved_lang = ""
        self._build_ui()
        self._load_current()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel(_("设置界面语言"))
        f = title.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 1)
        title.setFont(f)
        root.addWidget(title)

        desc = QLabel(_("选择后立即生效。"))
        desc.setStyleSheet("color: #5e5c64;")
        root.addWidget(desc)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        root.addWidget(line)

        self._group = QButtonGroup(self)
        self._radio_system = QRadioButton(_("跟随系统"))
        self._radio_zh = QRadioButton("中文")
        self._radio_en = QRadioButton("English")
        self._group.addButton(self._radio_system, 0)
        self._group.addButton(self._radio_zh, 1)
        self._group.addButton(self._radio_en, 2)

        radio_box = QVBoxLayout()
        radio_box.setSpacing(8)
        radio_box.addWidget(self._radio_system)
        radio_box.addWidget(self._radio_zh)
        radio_box.addWidget(self._radio_en)
        root.addLayout(radio_box)

        root.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(_("确定"))
        buttons.button(QDialogButtonBox.Cancel).setText(_("取消"))
        for btn in buttons.buttons():
            btn.setFixedHeight(BUTTON_HEIGHT)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load_current(self) -> None:
        settings = load_settings()
        lang = settings.get("language", None)
        if lang is None:
            lang = get_language()
        if lang == "zh_CN":
            self._radio_zh.setChecked(True)
        elif lang == "en":
            self._radio_en.setChecked(True)
        else:
            self._radio_system.setChecked(True)

    def _on_accept(self) -> None:
        if self._radio_zh.isChecked():
            new_lang = "zh_CN"
        elif self._radio_en.isChecked():
            new_lang = "en"
        else:
            new_lang = ""
        settings = load_settings()
        settings["language"] = new_lang
        save_settings(settings)
        set_language(new_lang, notify=True)
        self.accept()
