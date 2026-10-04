# -*- coding: utf-8 -*-
"""角色头顶的小气泡：显示一句话，过一会儿自动消失（不抢焦点）。"""

from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtCore import Qt, QTimer

BUBBLE_STYLE = """
QLabel#Speech {
    background: rgba(255, 255, 255, 245);
    border: 2px solid #ff9ed2;
    border-radius: 14px;
    color: #4a3b46;
    font-size: 13px;
    padding: 8px 12px;
}
"""


class SpeechBubble(QWidget):
    MAX_WIDTH = 250

    def __init__(self, parent=None):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("")
        self.label.setObjectName("Speech")
        self.label.setStyleSheet(BUBBLE_STYLE)
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(self.MAX_WIDTH)
        self.label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.label)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_text(self, text, ms=2500):
        if not text:
            return
        self.label.setText(text)
        self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(max(600, int(ms)))

    def place_above(self, anchor_left, anchor_top, anchor_width, screen):
        """把气泡摆到角色头顶上方并保持在屏幕内。"""
        w, h = self.width(), self.height()
        x = anchor_left + (anchor_width - w) // 2
        x = max(screen.left() + 4, min(x, screen.right() - w - 4))
        y = anchor_top - h - 6
        if y < screen.top() + 4:
            y = anchor_top + 8  # 头顶没地方就放到下方
        self.move(x, y)
