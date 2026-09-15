@echo off
setlocal
cd /d "%~dp0"

set "VENV_PYTHON=.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo Creating the Python virtual environment and installing dependencies...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
    if errorlevel 1 (
        echo.
        echo Setup failed. Install Python 3.10 or later, then run run.bat again.
        pause
        exit /b 1
    )
)

echo Starting IAM-ADSL at http://127.0.0.1:5001
"%VENV_PYTHON%" app.py

if errorlevel 1 (
    echo.
    echo IAM-ADSL stopped with an error.
    pause
)

endlocal
