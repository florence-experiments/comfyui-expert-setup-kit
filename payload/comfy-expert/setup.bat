@echo off
setlocal
cd /d "%~dp0"
title ComfyUI Expert - setup
echo.
echo === ComfyUI Expert setup ===
echo This creates its OWN Python environment in "%~dp0.venv".
echo It never installs anything into ComfyUI's python_embeded.
echo.

set "PYEXE="
for %%V in (3.12 3.11 3.13 3.10) do (
  if not defined PYEXE (
    py -%%V -c "import sys" >nul 2>&1 && set "PYEXE=py -%%V"
  )
)
if not defined PYEXE (
  python -c "import sys; assert sys.version_info >= (3,10); assert 'python_embeded' not in sys.executable.lower()" >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
  echo [!] Python 3.10 or newer was not found.
  echo     Install it from https://www.python.org/downloads/windows/  ^(tick "Add python.exe to PATH"^)
  echo     then run setup.bat again.
  pause
  exit /b 1
)
echo Using: %PYEXE%
%PYEXE% -c "import sys; print(sys.executable, sys.version)"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PYEXE% -m venv .venv || (echo [!] venv creation failed & pause & exit /b 1)
)
echo Installing requirements (a few minutes the first time)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo [!] pip install failed & pause & exit /b 1)

if not exist "config.yaml" (
  copy /y "config.example.yaml" "config.yaml" >nul
  echo Created config.yaml - check the folders in it.
)
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo Created .env - add API keys there if you have them ^(optional^).
)
echo.
echo Checking your setup:
".venv\Scripts\python.exe" -m comfy_expert doctor
echo.
echo Setup done. Start llama-server ^(start-llama.bat, written by the setup kit^), then double-click run.bat
pause
