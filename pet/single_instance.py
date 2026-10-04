# -*- coding: utf-8 -*-
"""单实例保护。

重复双击启动、或者「开机自启 + 手动再点一次」会跑出两只桌宠，
它们会同时读写 data/config.json 与 data/memory.json，互相覆盖。

这里用本地套接字（QLocalServer / QLocalSocket）：
* 第二个实例启动时先尝试连接，连上了就让已经在跑的那只露个面（打开聊天），
  自己直接退出；
* 连不上就自己占坑，并把「露个面」的请求接到回调上。
任何一步失败都只是放弃保护，不影响桌宠正常启动。
"""

import logging
from typing import Callable

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from .build_info import TTS_AVAILABLE

SERVER_NAME = f"KangelAmePet-{'tts' if TTS_AVAILABLE else 'no-tts'}"
log = logging.getLogger("pet.single")


def notify_existing(timeout_ms=400, name=SERVER_NAME):
    """已经在跑就通知它露个面，返回 True。"""
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(timeout_ms):
        return False
    try:
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(timeout_ms)
        sock.disconnectFromServer()
    except Exception as e:
        log.warning("通知已有实例失败: %s", e)
    return True


class SingleInstanceServer:
    """占用单实例套接字；收到其它实例的请求时调用 on_show。"""

    def __init__(self, on_show: Callable[[], None], name: str = SERVER_NAME) -> None:
        self.name = name
        self._server = None
        srv = QLocalServer()
        if not srv.listen(name):
            if notify_existing(name=name):
                return
            QLocalServer.removeServer(name)
            if srv.listen(name):
                srv.newConnection.connect(lambda: self._on_connection(srv, on_show))
                self._server = srv
                return
            log.warning("单实例监听失败，本次不做重复启动保护: %s", srv.errorString())
            return
        srv.newConnection.connect(lambda: self._on_connection(srv, on_show))
        self._server = srv
        log.info("单实例保护已启用")

    @staticmethod
    def _on_connection(srv, on_show):
        conn = srv.nextPendingConnection()
        if conn is None:
            return
        try:
            conn.waitForReadyRead(200)
            conn.readAll()
            conn.disconnectFromServer()
        except Exception:
            pass
        conn.deleteLater()
        try:
            on_show()
        except Exception:
            log.exception("处理重复启动请求失败")

    def close(self):
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(self.name)
            self._server = None
