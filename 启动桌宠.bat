@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".buildenv\Scripts\pythonw.exe" (
    start "" ".buildenv\Scripts\pythonw.exe" "main.py"
    exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "main.py"
    exit /b
)
echo 请先按 README.md 安装 Python 环境。
pause
