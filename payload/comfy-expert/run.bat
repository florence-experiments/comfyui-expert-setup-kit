@echo off
setlocal
cd /d "%~dp0"
title ComfyUI Expert
if not exist ".venv\Scripts\python.exe" (
  echo First run - running setup...
  call setup.bat || exit /b 1
)
echo Starting ComfyUI Expert at http://127.0.0.1:7860 ... (close this window to stop)
".venv\Scripts\python.exe" -m comfy_expert web %*
if errorlevel 1 pause
