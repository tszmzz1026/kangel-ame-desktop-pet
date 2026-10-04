# -*- coding: utf-8 -*-
"""对话面板：气泡显示 + 3 个选项 + 键盘输入。"""

from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QLabel,
    QSizePolicy,
    QWidget,
)
from PySide6.QtCore import Qt, QTimer, Signal


STYLE = """
QFrame#ChatPanel {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #fff8fd, stop:1 #ffeef8);
    border: 2px solid #ff9ed2;
    border-radius: 16px;
}
QLabel#Bubble {
    background: #ffffff;
    border: 2px solid #ffc2e2;
    border-radius: 12px;
    color: #4a3b46;
    font-size: 14px;
    padding: 10px;
}
QPushButton#Option {
    background: #ffffff;
    border: 2px solid #ffb3dd;
    border-radius: 12px;
    color: #b03a78;
    font-size: 13px;
    padding: 7px;
    text-align: left;
}
QPushButton#Option:hover { background: #ffe3f2; border-color:#ff7fc0; }
QLineEdit#Input {
    border: 2px solid #ffb3dd;
    border-radius: 12px;
    padding: 8px;
    font-size: 13px;
    background: #ffffff;
    color: #4a3b46;
}
QPushButton#Send {
    background: #ff7fc0;
    border: none;
    border-radius: 12px;
    color: white;
    font-size: 13px;
    padding: 8px 14px;
    font-weight: bold;
}
QPushButton#Send:hover { background: #ff5fb0; }
QPushButton#Close {
    background: transparent; border: none; color: #ff7fc0;
    font-size: 14px; font-weight: bold;
}
"""


class ChatPanel(QFrame):
    submitted = Signal(str)
    option_clicked = Signal(str)
    resized = Signal()

    PANEL_W = 400

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatPanel")
        self.setFixedWidth(self.PANEL_W)
        self.setStyleSheet(STYLE)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("♡ 超天酱 ♡")
        title.setStyleSheet(
            "color:#e0539c; font-weight:bold; font-size:14px; border:none; background:transparent;"
        )
        close = QPushButton("✕")
        close.setObjectName("Close")
        close.clicked.connect(self.hide)
        top.addWidget(title)
        top.addStretch()
        top.addWidget(close)
        lay.addLayout(top)

        self.bubble = QLabel("")
        self.bubble.setObjectName("Bubble")
        self.bubble.setWordWrap(True)
        self.bubble.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.bubble.setMinimumHeight(60)
        self.bubble.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        lay.addWidget(self.bubble)

        self.opt_buttons = []
        for i in range(3):
            b = QPushButton("")
            b.setObjectName("Option")
            b.hide()
            b.clicked.connect(lambda _=False, idx=i: self._on_option(idx))
            self.opt_buttons.append(b)
            lay.addWidget(b)

        inrow = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setObjectName("Input")
        self.input.setPlaceholderText("和超天酱说点什么…（回车发送）")
        self.input.returnPressed.connect(self._on_send)
        send = QPushButton("发送")
        send.setObjectName("Send")
        send.clicked.connect(self._on_send)
        inrow.addWidget(self.input)
        inrow.addWidget(send)
        lay.addLayout(inrow)

        # 打字机
        self._full_text = ""
        self._typed = 0
        self.type_timer = QTimer(self)
        self.type_timer.timeout.connect(self._type_step)

        self.adjustSize()

    def _on_send(self):
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.submitted.emit(text)

    def _on_option(self, idx):
        b = self.opt_buttons[idx]
        if b.isVisible():
            self.option_clicked.emit(b.text())

    def _esc(self, s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _render(self, jp, zh=None):
        html = f"<div style='font-size:14px; color:#4a3b46;'>{self._esc(jp)}</div>"
        if zh:
            html += f"<div style='font-size:11px; color:#a08a97; margin-top:5px;'>{self._esc(zh)}</div>"
        self.bubble.setText(html)

    def show_reply(self, reply: dict):
        self._full_text = reply.get("text", "")
        self._zh = reply.get("zh", "")
        self._typed = 0
        self._render("")
        self.type_timer.start(30)
        opts = reply.get("options", [])
        for i, b in enumerate(self.opt_buttons):
            if i < len(opts) and opts[i]:
                b.setText(opts[i])
                b.show()
            else:
                b.hide()
        self.adjustSize()
        self.show()
        self.raise_()
        self.resized.emit()

    def _type_step(self):
        self._typed += 2
        if self._typed >= len(self._full_text):
            self.type_timer.stop()
            self._render(self._full_text, self._zh)
        else:
            self._render(self._full_text[: self._typed])
        self.adjustSize()
        self.resized.emit()

    def show_waiting(self, hint="超天酱正在想你…"):
        self._full_text = hint
        self.bubble.setText(hint)
        for b in self.opt_buttons:
            b.hide()
        self.adjustSize()
        self.show()
        self.raise_()
        self.resized.emit()
