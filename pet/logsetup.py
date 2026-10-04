# -*- coding: utf-8 -*-
"""运行日志：统一落到 data/pet.log，并把 pythonw 下丢掉的标准输出接回来。

启动桌宠.bat 用的是 pythonw.exe，没有控制台：所有 print、以及 Qt 里未捕获的
异常都直接消失，出问题只能靠猜。这里：

* 日志滚动写入 data/pet.log（1MB × 2 份）；
* pythonw 下把 sys.stdout / sys.stderr 接到日志，原有的 print 立刻可见；
* 有控制台（调试模式.bat 用 python.exe）时保持原样，照旧打印到屏幕；
* 安装 sys.excepthook 与 Qt 消息处理器，异常和 Qt 警告也进日志。
"""

import logging
import logging.handlers
import os
import sys

from . import config

LOG_PATH = os.path.join(config.DATA_DIR, "pet.log")
_installed = False


class _StreamToLog:
    """把 print 的写入转成日志行（pythonw 没有 stdout 时使用）。"""

    def __init__(self, logger, level):
        self._logger = logger
        self._level = level
        self._buf = ""

    def write(self, s):
        try:
            if not isinstance(s, str):
                return
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    self._logger.log(self._level, line.rstrip())
        except Exception:
            pass

    def flush(self):
        try:
            if self._buf.strip():
                self._logger.log(self._level, self._buf.rstrip())
            self._buf = ""
        except Exception:
            pass

    def isatty(self):
        return False

    def writable(self):
        return True


def _excepthook(exc_type, exc, tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logging.getLogger("pet").error("未捕获的异常", exc_info=(exc_type, exc, tb))


def _qt_message_handler(mode, context, message):
    logging.getLogger("qt").warning("%s", message)
    # 有控制台时保持 Qt 原本的可见性（pythonw 下 __stderr__ 为 None）
    try:
        stream = sys.__stderr__
        if stream is not None:
            print("Qt:", message, file=stream, flush=True)
    except Exception:
        pass


def install(level=logging.INFO):
    """安装日志（可重复调用）。返回桌宠自己的 logger。"""
    global _installed
    log = logging.getLogger("pet")
    if _installed:
        return log
    _installed = True

    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    try:
        handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(fmt)
        root.addHandler(handler)
    except Exception:
        pass

    if sys.stdout is None:  # pythonw：没有控制台
        sys.stdout = _StreamToLog(logging.getLogger("stdout"), logging.INFO)
    if sys.stderr is None:
        sys.stderr = _StreamToLog(logging.getLogger("stderr"), logging.WARNING)

    sys.excepthook = _excepthook
    try:
        from PySide6.QtCore import qInstallMessageHandler

        qInstallMessageHandler(_qt_message_handler)
    except Exception:
        pass

    log.info("==== 桌宠启动 · 日志 %s ====", LOG_PATH)
    return log


def log_path():
    return LOG_PATH
