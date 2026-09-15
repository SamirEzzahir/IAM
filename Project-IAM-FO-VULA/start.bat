@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher "py" was not found. Install Python 3.10 or newer.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the Python virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 goto :error
    set "INSTALL_DEPENDENCIES=1"
)

if not defined INSTALL_DEPENDENCIES (
    ".venv\Scripts\python.exe" -c "import flask, selenium" >nul 2>nul
    if errorlevel 1 set "INSTALL_DEPENDENCIES=1"
)

if defined INSTALL_DEPENDENCIES (
    echo Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

echo.
echo VULA Control Center is starting at http://127.0.0.1:5000
echo Press Ctrl+C to stop it.
echo.
".venv\Scripts\python.exe" app.py
exit /b %errorlevel%

:error
echo.
echo Unable to start VULA Control Center. Review the error above.
pause
exit /b 1
