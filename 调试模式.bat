@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".buildenv\Scripts\python.exe" (
    ".buildenv\Scripts\python.exe" "main.py"
) else if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "main.py"
) else (
    echo 请先按 README.md 安装 Python 环境。
)
pause
