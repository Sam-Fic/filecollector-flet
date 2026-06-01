from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLineEdit, QLabel,
    QInputDialog, QMessageBox, QDialogButtonBox
)
from PySide6.QtCore import Qt


class PhrasesDialog(QDialog):
    phrase_selected = None

    def __init__(self, phrases: list[str], parent=None, select_mode: bool = False):
        super().__init__(parent)
        self.setWindowTitle("插入常用语" if select_mode else "常用语管理")
        self.resize(440, 360)
        self.setModal(True)
        self._select_mode = select_mode
        self._phrases = list(phrases or [])

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        self.list_widget = QListWidget()
        self._reload()
        root.addWidget(self.list_widget)

        if not select_mode:
            row = QHBoxLayout()
            btn_add = QPushButton("新增")
            btn_edit = QPushButton("编辑")
            btn_delete = QPushButton("删除")
            btn_close = QPushButton("关闭")
            btn_add.clicked.connect(self._on_add)
            btn_edit.clicked.connect(self._on_edit)
            btn_delete.clicked.connect(self._on_delete)
            btn_close.clicked.connect(self.reject)
            row.addWidget(btn_add)
            row.addWidget(btn_edit)
            row.addWidget(btn_delete)
            row.addStretch()
            row.addWidget(btn_close)
            root.addLayout(row)
        else:
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(self._on_accept)
            buttons.rejected.connect(self.reject)
            root.addWidget(buttons)

    def _reload(self) -> None:
        self.list_widget.clear()
        if not self._phrases:
            item = QListWidgetItem("暂无常用语")
            item.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(item)
            return
        for text in self._phrases:
            self.list_widget.addItem(text)

    def _current_text(self) -> str | None:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._phrases):
            return self._phrases[row]
        return None

    def _on_add(self) -> None:
        text, ok = QInputDialog.getText(self, "新增常用语", "文本")
        if ok and text.strip():
            self._phrases.append(text.strip())
            self._reload()
            self._persist()

    def _on_edit(self) -> None:
        current = self._current_text()
        if current is None:
            return
        text, ok = QInputDialog.getText(self, "编辑常用语", "文本", text=current)
        if ok and text.strip():
            idx = self._phrases.index(current)
            self._phrases[idx] = text.strip()
            self._reload()
            self._persist()

    def _on_delete(self) -> None:
        current = self._current_text()
        if current is None:
            return
        if QMessageBox.question(self, "确认", "删除选中常用语？") != QMessageBox.Yes:
            return
        self._phrases.remove(current)
        self._reload()
        self._persist()

    def _on_accept(self) -> None:
        text = self._current_text()
        if text is not None:
            PhrasesDialog.phrase_selected = text
        else:
            PhrasesDialog.phrase_selected = None
        self.accept()

    def _persist(self) -> None:
        try:
            from filecollector.config import get_common_phrases_path
            Path(get_common_phrases_path()).write_text(
                json.dumps(self._phrases, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    def phrases(self) -> list[str]:
        return list(self._phrases)
