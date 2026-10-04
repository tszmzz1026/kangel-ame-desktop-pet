# -*- coding: utf-8 -*-
"""超天酱桌宠 - 程序入口。"""

import argparse
import os, sys
from pathlib import Path

# 确保项目根目录在 sys.path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from pet import logsetup
from pet.config import load_config
from pet.pet_window import PetWindow
from pet.build_info import APP_NAME, VERSION
from pet.process_exit import exit_process


def main() -> None:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--self-test", type=Path)
    args = parser.parse_args()
    # 日志要最先装好：后面任何一步出错（包括 Qt 里的异常）都能落到 data/pet.log
    log = logsetup.install()

    # 高 DPI 支持（PySide6 默认开启，这里仅确保策略）
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setQuitOnLastWindowClosed(False)

    # 单实例保护：已经在跑就让它露个面，然后自己退出。
    # 否则两只桌宠会同时读写 data/config.json 与 data/memory.json。
    notify_existing = None
    SingleInstanceServer = None
    try:
        from pet.single_instance import notify_existing, SingleInstanceServer
    except Exception as e:
        log.warning("单实例模块不可用（跳过保护）: %s", e)

    if args.self_test is None and notify_existing is not None:
        try:
            if notify_existing():
                log.info("已经有一只超天酱在运行，本次启动直接退出")
                os._exit(0)
        except Exception as e:
            log.warning("单实例检查失败（忽略）: %s", e)

    server = None
    if args.self_test is None and SingleInstanceServer is not None:
        try:
            server = SingleInstanceServer(lambda: win.open_chat())
            if server._server is None:
                os._exit(0 if notify_existing() else 1)
        except Exception as e:
            log.warning("单实例监听建立失败（忽略）: %s", e)

    cfg = load_config()
    if args.self_test is not None:
        cfg["tts"]["enabled"] = False
        cfg["tts"]["auto_start_api"] = False
        cfg["vision"]["enabled"] = False
        cfg["vision"]["proactive_comment"] = False
        cfg["behavior"]["sleep_enabled"] = False
    win = PetWindow(cfg)
    win.show()
    result = {"ok": True}

    def finish_app() -> None:
        if server is not None:
            server.close()
        for handler in log.root.handlers:
            handler.flush()
        exit_process(0 if result["ok"] else 1)

    win._exit_callback = finish_app
    if args.self_test is not None:
        from pet.self_test import schedule_self_test

        schedule_self_test(win, args.self_test, result)
    app.exec()
    win.tts.close()
    # 立即结束进程，绕过原生库（SSL/PortAudio 等）解释器退出清理可能导致的崩溃。
    # 配置与记忆已在退出前写盘，日志按行即时落盘，可安全直接结束。
    finish_app()


if __name__ == "__main__":
    main()
