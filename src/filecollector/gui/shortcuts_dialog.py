from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QLabel, QFrame,
    QDialogButtonBox
)
from PySide6.QtCore import Qt

from filecollector.i18n import _
from filecollector.config import BUTTON_HEIGHT


def _build_shortcut_groups():
    return [
        {
            "label": _("常用操作"),
            "items": [
                (_("撤销"), "Ctrl+Z"),
                (_("重做"), "Ctrl+Shift+Z"),
                (_("打开项目"), "Ctrl+O"),
                (_("保存项目"), "Ctrl+S"),
                (_("清空列表"), "Ctrl+N"),
                (_("添加外部文件"), "Ctrl+E"),
            ],
        },
        {
            "label": _("列表操作"),
            "items": [
                (_("上方插入文本"), "Ctrl+I"),
                (_("下方插入文本"), "Ctrl+Shift+I"),
                (_("上移"), "Ctrl+Up"),
                (_("下移"), "Ctrl+Down"),
                (_("删除"), "Delete"),
                (_("生成合并文本"), "Ctrl+G"),
                (_("生成到剪贴板"), "Ctrl+Shift+C"),
            ],
        },
        {
            "label": _("应用程序"),
            "items": [
                (_("语言设置"), "Ctrl+,"),
                (_("键盘快捷键"), "Ctrl+/"),
                (_("关于"), "F1"),
                (_("退出"), "Ctrl+Q"),
            ],
        },
    ]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("键盘快捷键"))
        self.resize(420, 380)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("<b>" + _("键盘快捷键") + "</b>")
        root.addWidget(title)

        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setColumnCount(2)
        tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)

        for group in _build_shortcut_groups():
            group_item = QTreeWidgetItem([f"<b>{group['label']}</b>", ""])
            group_item.setFlags(Qt.ItemIsEnabled)
            tree.addTopLevelItem(group_item)
            for name, shortcut in group["items"]:
                item = QTreeWidgetItem([name, shortcut])
                tree.addTopLevelItem(item)

        tree.resizeColumnToContents(0)
        root.addWidget(tree)

        close_btn = QDialogButtonBox(QDialogButtonBox.Close)
        close_btn.button(QDialogButtonBox.Close).setText(_("关闭"))
        close_btn.button(QDialogButtonBox.Close).setFixedHeight(BUTTON_HEIGHT)
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn)
