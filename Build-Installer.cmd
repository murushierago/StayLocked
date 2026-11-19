@echo off
cd /d "%~dp0"
call Build-StayLocked.cmd --installer
exit /b %errorlevel%
