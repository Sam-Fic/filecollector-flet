import sys
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QHBoxLayout, QVBoxLayout,
    QGraphicsOpacityEffect
)


class ToastNotification(QWidget):
    """轻量级非阻塞 Toast 通知组件."""

    DEFAULT_DURATION = 2000

    def __init__(self, text, parent=None, duration=DEFAULT_DURATION):
        super().__init__(parent)
        self._text = text
        self._duration = duration
        self._positioned = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.SubWindow |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._setup_ui()
        self._setup_animation()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        container = QWidget()
        container.setObjectName("ToastContainer")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(16, 10, 16, 10)
        container_layout.setSpacing(4)

        icon_label = QLabel("ℹ️")
        icon_label.setStyleSheet("background: transparent; border: none; font-size: 14px;")
        container_layout.addWidget(icon_label)

        text_label = QLabel(self._text)
        text_label.setWordWrap(True)
        text_label.setStyleSheet(
            "background-color: #2d2d2d; "
            "color: #ffffff; "
            "font-size: 13px; "
            "padding: 4px; "
            "border: none;"
        )
        container_layout.addWidget(text_label)

        container.setStyleSheet(
            "#ToastContainer {"
            "  background-color: #2d2d2d; "
            "  border-radius: 10px; "
            "  border: 1px solid #444444;"
            "}"
        )
        layout.addWidget(container)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)

        self._fade_in = QPropertyAnimation(self._effect, b"opacity")
        self._fade_in.setDuration(250)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._fade_out = QPropertyAnimation(self._effect, b"opacity")
        self._fade_out.setDuration(250)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(self._on_fade_out_finished)

    def _setup_animation(self):
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._start_fade_out)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._positioned:
            self._position_to_parent()
            self._positioned = True
        self._fade_in.start()
        self._dismiss_timer.start(self._duration)

    def _position_to_parent(self):
        parent = self.parent()
        if parent is None:
            return
        parent_geom = parent.geometry()
        toast_size = self.sizeHint()
        margin = 24
        x = parent_geom.x() + (parent_geom.width() - toast_size.width()) // 2
        y = parent_geom.y() + parent_geom.height() - toast_size.height() - margin
        self.move(QPoint(max(parent_geom.x(), x), y))

    def _start_fade_out(self):
        if self._fade_out.state() == QPropertyAnimation.State.Running:
            return
        self._fade_out.start()

    def _on_fade_out_finished(self):
        self.close()
        self.deleteLater()

    @staticmethod
    def show_toast(text, parent=None, duration=DEFAULT_DURATION):
        toast = ToastNotification(text, parent, duration)
        toast.show()
        return toast
