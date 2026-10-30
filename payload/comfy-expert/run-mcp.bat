@echo off
setlocal
cd /d "%~dp0"
title ComfyUI Expert MCP server
if not exist ".venv\Scripts\python.exe" call setup.bat
rem Default: streamable HTTP on this computer only (127.0.0.1:8765/mcp).
rem For OpenHands in Docker use: run-mcp.bat --transport http --host 0.0.0.0  (and set MCP_TOKEN in .env first)
rem Other examples:
rem   run-mcp.bat --transport sse --host 0.0.0.0 --port 8765     (legacy SSE: /sse)
rem   run-mcp.bat --transport http --host 127.0.0.1               (local clients only)
rem Set MCP_TOKEN in .env (or mcp.token in config.yaml) to require a bearer token.
if "%~1"=="" (
  ".venv\Scripts\python.exe" -m comfy_expert mcp --transport http --host 127.0.0.1
) else (
  ".venv\Scripts\python.exe" -m comfy_expert mcp %*
)
pause
