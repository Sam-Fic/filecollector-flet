from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QLabel, QFrame,
    QDialogButtonBox
)
from PySide6.QtCore import Qt


_SHORTCUT_GROUPS = [
    {
        "label": "常用操作",
        "items": [
            ("撤销", "Ctrl+Z"),
            ("重做", "Ctrl+Shift+Z"),
            ("打开项目", "Ctrl+O"),
            ("保存项目", "Ctrl+S"),
            ("清空列表", "Ctrl+N"),
            ("添加外部文件", "Ctrl+E"),
        ],
    },
    {
        "label": "列表操作",
        "items": [
            ("上方插入文本", "Ctrl+I"),
            ("下方插入文本", "Ctrl+Shift+I"),
            ("上移", "Ctrl+Up"),
            ("下移", "Ctrl+Down"),
            ("删除", "Delete"),
            ("生成合并文本", "Ctrl+G"),
            ("生成到剪贴板", "Ctrl+Shift+C"),
        ],
    },
    {
        "label": "应用程序",
        "items": [
            ("语言设置", "Ctrl+,"),
            ("键盘快捷键", "Ctrl+/"),
            ("关于", "F1"),
            ("退出", "Ctrl+Q"),
        ],
    },
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("键盘快捷键")
        self.resize(420, 380)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("<b>键盘快捷键</b>")
        root.addWidget(title)

        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setColumnCount(2)
        tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)

        for group in _SHORTCUT_GROUPS:
            group_item = QTreeWidgetItem([f"<b>{group['label']}</b>", ""])
            group_item.setFlags(Qt.ItemIsEnabled)
            tree.addTopLevelItem(group_item)
            for name, shortcut in group["items"]:
                item = QTreeWidgetItem([name, shortcut])
                tree.addTopLevelItem(item)

        tree.resizeColumnToContents(0)
        root.addWidget(tree)

        close_btn = QDialogButtonBox(QDialogButtonBox.Close)
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn)
