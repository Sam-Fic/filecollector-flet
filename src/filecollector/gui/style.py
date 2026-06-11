"""GNOME Human Interface Guidelines 风格的 Qt 样式表.

参考 GNOME 版本 (Adwaita/GTK4) 的视觉语言:
- 圆角卡片式面板
- 移除默认焦点轮廓
- 列表项悬浮 / 选中效果
- 主操作按钮使用品牌强调色
"""

STYLESHEET = """
/* ---- 全局基线 ---- */
QMainWindow, QDialog {
    background-color: #f6f5f4;
}

/* ---- 三栏卡片 ---- */
QFrame#LeftPanel,
QFrame#MiddlePanel,
QFrame#RightPanel {
    background-color: #ffffff;
    border: 1px solid #dcd9d6;
    border-radius: 9px;
}

QLabel#PanelTitle {
    font-weight: bold;
    color: #2e2e2e;
    padding: 10px 12px 10px 12px;
    background: transparent;
    border: none;
    qproperty-alignment: AlignCenter;
}

/* ---- 工具栏 ---- */
QToolBar {
    background: transparent;
    border: none;
    spacing: 4px;
    padding: 4px 8px;
}

QToolBar QLabel#WorkDirLabel {
    color: #1c71d8;
    font-weight: 600;
    padding: 0 8px;
}

QToolBar QPushButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 12px;
    text-align: center;
}

QToolBar QPushButton:hover {
    background-color: rgba(28, 113, 216, 0.08);
}

QToolBar QPushButton:pressed {
    background-color: rgba(28, 113, 216, 0.16);
}

QToolBar QPushButton:disabled {
    color: #b0afad;
}

/* ---- 主操作按钮 (suggested-action) ---- */
QPushButton#SuggestedAction {
    background-color: #1c71d8;
    color: #ffffff;
    border: 1px solid #1a68c2;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 600;
    text-align: center;
}

QPushButton#SuggestedAction:hover {
    background-color: #1a68c2;
}

QPushButton#SuggestedAction:pressed {
    background-color: #1859ad;
}

QPushButton#SuggestedAction:disabled {
    background-color: #b6d4f1;
    color: #ffffff;
    border-color: #b6d4f1;
}

/* ---- 危险操作按钮 (destructive-action) ---- */
QPushButton#DestructiveAction {
    background-color: #c01c28;
    color: #ffffff;
    border: 1px solid #b01a25;
    border-radius: 6px;
    padding: 6px 12px;
    text-align: center;
}

QPushButton#DestructiveAction:hover {
    background-color: #b01a25;
}

QPushButton#DestructiveAction:pressed {
    background-color: #9c1720;
}

QPushButton#DestructiveAction:disabled {
    background-color: #e8a4a8;
    color: #ffffff;
    border-color: #e8a4a8;
}

/* ---- 平面按钮 ---- */
QPushButton#FlatButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 12px;
    text-align: center;
}

QPushButton#FlatButton:hover {
    background-color: rgba(28, 113, 216, 0.08);
}

QPushButton#FlatButton:pressed {
    background-color: rgba(28, 113, 216, 0.16);
}

/* ---- 通用按钮 ---- */
QPushButton {
    background-color: #ffffff;
    border: 1px solid #dcd9d6;
    border-radius: 6px;
    padding: 5px 12px;
    color: #2e2e2e;
    text-align: center;
}

QPushButton:hover {
    border-color: #b6b3af;
    background-color: #fafaf9;
}

QPushButton:pressed {
    background-color: #efeeec;
}

QPushButton:disabled {
    color: #b0afad;
    background-color: #f6f5f4;
}

/* ---- 文件树 ---- */
QTreeWidget {
    background: transparent;
    border: none;
    outline: 0;
}

QTreeWidget::item {
    padding: 3px 4px;
    border-radius: 4px;
}

QTreeWidget::item:hover {
    background-color: rgba(28, 113, 216, 0.08);
}

QTreeWidget::item:selected {
    background-color: rgba(28, 113, 216, 0.18);
}

QTreeWidget::branch {
    background: transparent;
}

/* ---- 列表 ---- */
QListWidget {
    background: transparent;
    border: none;
    outline: 0;
    padding: 0px 12px;
}

QListWidget::item {
    padding: 6px 12px;
    border-radius: 6px;
}

QListWidget::item:hover {
    background-color: rgba(28, 113, 216, 0.08);
}

QListWidget::item:selected {
    background-color: rgba(28, 113, 216, 0.20);
    color: #2e2e2e;
}

/* ---- 预览文本 ---- */
QTextEdit#PreviewView {
    background: transparent;
    border: none;
    padding: 0px 12px;
    font-size: 12px;
    color: #2e2e2e;
    selection-background-color: #1c71d8;
    selection-color: #ffffff;
}

/* ---- 搜索框 ---- */
QLineEdit {
    background-color: #ffffff;
    border: 1px solid #dcd9d6;
    border-radius: 6px;
    padding: 5px 10px;
    color: #2e2e2e;
}

QLineEdit:focus {
    border-color: #1c71d8;
}

/* ---- 复选框 / 单选 ---- */
QCheckBox, QRadioButton {
    spacing: 6px;
    color: #2e2e2e;
}

QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
}

/* ---- 状态栏 ---- */
QStatusBar {
    background: transparent;
    color: #5e5c64;
}

/* ---- 分隔条 ---- */
QSplitter::handle {
    background: transparent;
}

/* ---- 滚动条 ---- */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: rgba(0, 0, 0, 0.20);
    border-radius: 5px;
    min-height: 20px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background: rgba(0, 0, 0, 0.35);
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: rgba(0, 0, 0, 0.20);
    border-radius: 5px;
    min-width: 20px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background: rgba(0, 0, 0, 0.35);
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ---- 菜单 ---- */
QMenuBar {
    background: transparent;
    color: #2e2e2e;
}

QMenuBar::item {
    background: transparent;
    padding: 4px 10px;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background-color: rgba(28, 113, 216, 0.10);
}

QMenu {
    background-color: #ffffff;
    border: 1px solid #dcd9d6;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 5px 22px 5px 22px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: rgba(28, 113, 216, 0.15);
}
"""


def get_stylesheet() -> str:
    """返回完整样式表."""
    return STYLESHEET
