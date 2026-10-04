# -*- coding: utf-8 -*-
"""开机自启动：写入/删除 HKCU 注册表 Run 项。"""

import os
import subprocess
import sys
import winreg

from .config import APP_DIR

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ChouzetsuTenshiPet"


def _build_command() -> str:
    if getattr(sys, "frozen", False):
        return subprocess.list2cmdline([sys.executable])
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    main_py = os.path.join(APP_DIR, "main.py")
    return subprocess.list2cmdline([pythonw if os.path.exists(pythonw) else sys.executable, main_py])


def is_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, VALUE_NAME)
            return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def enable():
    cmd = _build_command()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, cmd)
    return True


def disable():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, VALUE_NAME)
    except FileNotFoundError:
        pass
    return True


def set_autostart(on):
    return enable() if on else disable()
