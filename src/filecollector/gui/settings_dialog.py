"""语言设置对话框 (替换原有占位 MessageBox).

提供 跟随系统 / 中文 / English 三个互斥选项, 选中后写入配置文件.
选择立即重启时使用 QProcess 启动新进程并退出当前进程.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QProcess
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QButtonGroup, QRadioButton,
    QDialogButtonBox, QLabel, QFrame, QMessageBox, QApplication,
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
        lang = settings.get("language", "") or get_language()
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

        reply = QMessageBox.question(
            self,
            _("提示"),
            _("语言设置已保存，重启应用后生效。是否现在重启？"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            self._restart_application()
            return
        self.accept()

    def _restart_application(self) -> None:
        """使用 QProcess 启动新进程并退出当前进程."""
        try:
            self.accept()
            python = sys.executable
            script = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "__main__.py")
            )
            QProcess.startDetached(python, [script])
        except Exception:
            pass
        QApplication.quit()
