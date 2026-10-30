@echo off
setlocal
cd /d "%~dp0"
title ComfyUI Expert (terminal)
if not exist ".venv\Scripts\python.exe" call setup.bat
chcp 65001 >nul
".venv\Scripts\python.exe" -m comfy_expert chat %*
pause
