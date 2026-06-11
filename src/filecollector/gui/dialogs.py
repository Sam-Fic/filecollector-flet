"""文字编辑/插入对话框.

行为对齐 GNOME 版本的 insert_text():
- 支持多行输入
- 提供"常用语"按钮, 弹出选择器后可一键填入选中常用语
- 接受/取消按钮使用 SuggestedAction 强调色
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton,
)

from filecollector.i18n import _
from filecollector.config import BUTTON_HEIGHT


class TextEditDialog(QDialog):
    """文字编辑/插入对话框."""

    def __init__(self, parent=None, title: str | None = None, initial_text: str = "",
                 show_phrases_button: bool = True, common_phrases: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle(title or _("编辑文字"))
        self.setModal(True)
        self.resize(500, 360)
        self.setMinimumSize(360, 240)

        self._common_phrases = list(common_phrases or [])
        self._show_phrases_button = bool(show_phrases_button)

        self._build_ui(initial_text)

    def _build_ui(self, initial_text: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(self.windowTitle())
        f = title.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 1)
        title.setFont(f)
        root.addWidget(title)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlainText(initial_text)
        root.addWidget(self.text_edit)

        row = QHBoxLayout()
        if self._show_phrases_button:
            self.phrases_btn = QPushButton(_("常用语"))
            self.phrases_btn.setFixedHeight(BUTTON_HEIGHT)
            self.phrases_btn.clicked.connect(self._open_phrases_picker)
            row.addWidget(self.phrases_btn)
        row.addStretch()
        self.cancel_btn = QPushButton(_("取消"))
        self.cancel_btn.setFixedHeight(BUTTON_HEIGHT)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn = QPushButton(_("确定"))
        self.ok_btn.setObjectName("SuggestedAction")
        self.ok_btn.setFixedHeight(BUTTON_HEIGHT)
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.accept)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.ok_btn)
        root.addLayout(row)

    def set_text(self, text: str) -> None:
        """覆盖当前文本."""
        self.text_edit.setPlainText(text)

    def get_text(self) -> str:
        return self.text_edit.toPlainText().strip()

    def _open_phrases_picker(self) -> None:
        from filecollector.gui.phrases_dialog import PhrasesDialog
        dlg = PhrasesDialog(self._common_phrases, self, select_mode=True)
        if dlg.exec() == QDialog.Accepted and dlg.phrase_selected:
            current = self.text_edit.toPlainText()
            new_text = current + ("\n" if current and not current.endswith("\n") else "") + dlg.phrase_selected
            self.text_edit.setPlainText(new_text)
            self.text_edit.moveCursor(self.text_edit.textCursor().End)
