"""在数据落盘后退出当前进程，避开 Windows DLL 的退出清理崩溃。"""

import ctypes
import os
import sys
from ctypes import wintypes


def exit_process(exit_code: int) -> None:
    if sys.platform == "win32":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel.TerminateProcess.restype = wintypes.BOOL
        kernel.TerminateProcess(kernel.GetCurrentProcess(), exit_code)
    os._exit(exit_code)
