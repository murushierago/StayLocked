@echo off
setlocal
cd /d "%~dp0"
if exist "dist\StayLocked\StayLocked.exe" (
  start "" "dist\StayLocked\StayLocked.exe"
  exit /b 0
)
if exist ".venv\Scripts\python.exe" (
  powershell.exe -NoProfile -Command "Start-Process -FilePath '.\.venv\Scripts\python.exe' -ArgumentList 'start_focuslock.py' -WorkingDirectory (Get-Location).Path -Verb RunAs"
  exit /b %errorlevel%
)
echo Build and install the app first: double-click Build-Installer.cmd.
pause
