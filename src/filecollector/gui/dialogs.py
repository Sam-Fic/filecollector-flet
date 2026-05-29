from PySide6.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QPlainTextEdit, QDialogButtonBox
)


class TextEditDialog(QDialog):
    def __init__(self, parent=None, title="编辑文字", initial_text=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(500, 400)
        self.setMinimumSize(300, 200)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("请输入文字:"))

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlainText(initial_text)
        layout.addWidget(self.text_edit)

        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_text(self):
        return self.text_edit.toPlainText().strip()
