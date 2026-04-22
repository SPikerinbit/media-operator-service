@echo off
setlocal

set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_media_full_stack.ps1"

if errorlevel 1 (
  echo.
  echo Startup failed. Check logs in project root: server.err.log / server.out.log
  pause
  exit /b 1
)

exit /b 0
