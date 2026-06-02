"""常用语选择与管理对话框.

设计目标: 与 GNOME 版本 PhrasesPicker 行为一致.
- 选择模式 (select_mode=True): 单击条目即返回该条目 (用于"插入常用语"按钮).
- 管理模式 (select_mode=False): 提供 新增 / 编辑 / 删除 / 关闭 操作.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel,
    QInputDialog, QMessageBox, QDialogButtonBox, QFrame,
    QTextEdit, QDialogButtonBox as _DBB,
)

from filecollector.i18n import _
from filecollector.config import get_common_phrases_path


class PhrasesDialog(QDialog):
    """常用语选择 / 管理对话框."""

    phrase_selected: str | None = None

    def __init__(self, phrases: list[str], parent=None, select_mode: bool = False):
        super().__init__(parent)
        self._select_mode = bool(select_mode)
        self._phrases: list[str] = list(phrases or [])

        self.setWindowTitle(_("插入常用语") if self._select_mode else _("常用语管理"))
        self.setModal(True)
        self.resize(460, 380)
        self.setMinimumSize(360, 280)

        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(_("插入常用语") if self._select_mode else _("常用语管理"))
        f = title.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 1)
        title.setFont(f)
        root.addWidget(title)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        if self._select_mode:
            self.list_widget.itemDoubleClicked.connect(self._on_accept)
        root.addWidget(self.list_widget)

        if self._select_mode:
            row = QHBoxLayout()
            self._btn_new = QPushButton(_("添加"))
            self._btn_new.clicked.connect(self._on_add)
            cancel_btn = QPushButton(_("取消"))
            cancel_btn.clicked.connect(self.reject)
            ok_btn = QPushButton(_("确定"))
            ok_btn.setObjectName("SuggestedAction")
            ok_btn.clicked.connect(self._on_accept)
            row.addWidget(self._btn_new)
            row.addStretch()
            row.addWidget(cancel_btn)
            row.addWidget(ok_btn)
            root.addLayout(row)
        else:
            row = QHBoxLayout()
            self._btn_new = QPushButton(_("添加"))
            self._btn_new.clicked.connect(self._on_add)
            self._btn_edit = QPushButton(_("编辑"))
            self._btn_edit.clicked.connect(self._on_edit)
            self._btn_delete = QPushButton(_("删除"))
            self._btn_delete.setObjectName("DestructiveAction")
            self._btn_delete.clicked.connect(self._on_delete)
            self._btn_close = QPushButton(_("关闭"))
            self._btn_close.clicked.connect(self.accept)
            row.addWidget(self._btn_new)
            row.addWidget(self._btn_edit)
            row.addWidget(self._btn_delete)
            row.addStretch()
            row.addWidget(self._btn_close)
            root.addLayout(row)

        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        self._on_selection_changed()

    def _on_selection_changed(self, *_):
        has = self.list_widget.currentRow() >= 0
        if not self._select_mode:
            self._btn_edit.setEnabled(has)
            self._btn_delete.setEnabled(has)

    def _reload(self) -> None:
        self.list_widget.clear()
        if not self._phrases:
            placeholder = QListWidgetItem(_("暂无常用语"))
            placeholder.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(placeholder)
            return
        for text in self._phrases:
            display = text if len(text) <= 60 else text[:60] + "..."
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, text)
            item.setToolTip(text)
            self.list_widget.addItem(item)

    def _current_text(self) -> str | None:
        item = self.list_widget.currentItem()
        if not item:
            return None
        return item.data(Qt.UserRole)

    def _on_add(self) -> None:
        text, ok = self._ask_text(_("新增常用语"))
        if ok and text:
            self._phrases.append(text)
            self._reload()
            self._persist()
            self.list_widget.setCurrentRow(len(self._phrases) - 1)

    def _on_edit(self) -> None:
        current = self._current_text()
        if current is None:
            return
        text, ok = self._ask_text(_("编辑常用语"), current)
        if ok and text:
            idx = self._phrases.index(current)
            self._phrases[idx] = text
            self._reload()
            self._persist()
            self.list_widget.setCurrentRow(idx)

    def _on_delete(self) -> None:
        current = self._current_text()
        if current is None:
            return
        if QMessageBox.question(self, _("确认"), _("删除选中常用语？")) != QMessageBox.Yes:
            return
        self._phrases.remove(current)
        self._reload()
        self._persist()

    def _on_accept(self) -> None:
        if self._select_mode:
            text = self._current_text()
            if text is not None:
                PhrasesDialog.phrase_selected = text
            else:
                PhrasesDialog.phrase_selected = None
        self.accept()

    def _ask_text(self, title: str, default: str = "") -> tuple[str, bool]:
        """弹出多行输入对话框, 返回 (text, accepted)."""
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setModal(True)
        dlg.resize(500, 320)
        dlg.setMinimumSize(360, 220)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        text = QTextEdit()
        text.setPlainText(default)
        text.setAcceptRichText(False)
        layout.addWidget(text)

        row = QHBoxLayout()
        row.addStretch()
        cancel_btn = QPushButton(_("取消"))
        cancel_btn.clicked.connect(dlg.reject)
        ok_btn = QPushButton(_("确定"))
        ok_btn.setObjectName("SuggestedAction")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(dlg.accept)
        row.addWidget(cancel_btn)
        row.addWidget(ok_btn)
        layout.addLayout(row)

        ok = dlg.exec() == QDialog.Accepted
        if not ok:
            return "", False
        result = text.toPlainText().strip()
        return (result, bool(result))

    def _persist(self) -> None:
        try:
            Path(get_common_phrases_path()).write_text(
                json.dumps(self._phrases, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def phrases(self) -> list[str]:
        return list(self._phrases)
