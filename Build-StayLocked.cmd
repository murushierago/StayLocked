@echo off
setlocal
cd /d "%~dp0"
echo StayLocked - Windows EXE builder
echo Close the old StayLocked interface and finish any active session before building.
echo.
if exist ".build-venv\Scripts\python.exe" goto install
if exist ".venv\Scripts\python.exe" goto fromvenv
py -3 -m venv .build-venv
if not errorlevel 1 goto install
python -m venv .build-venv
if errorlevel 1 goto failed
goto install
:fromvenv
".venv\Scripts\python.exe" -m venv .build-venv
if errorlevel 1 goto failed
:install
".build-venv\Scripts\python.exe" -c "import sys; assert (3,12) <= sys.version_info < (3,15), 'Use Python 3.12, 3.13 or 3.14 to build'"
if errorlevel 1 goto failed
".build-venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
".build-venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto failed
".build-venv\Scripts\python.exe" tools\build_exe.py
if errorlevel 1 goto failed
echo.
if /I "%~1"=="--installer" goto installer
echo EXE BUILD COMPLETE. Run Build-Installer.cmd to install the required service.
echo The source and dist folders alone cannot install a SYSTEM service safely.
start "" explorer.exe "%CD%\dist\StayLocked"
pause
exit /b 0
:installer
".build-venv\Scripts\python.exe" tools\build_installer.py
if errorlevel 1 goto failed
pause
exit /b 0
:failed
echo.
echo BUILD FAILED. Send the error above (and build.log if present).
echo Do not run an old EXE as if it were a new successful build.
pause
exit /b 1
