@echo off
setlocal
cd /d "%~dp0"

title FO Services Portal

call :select_python
if errorlevel 1 goto :error

call :ensure_environment "Project-IAM-FO-VULA" "flask, selenium" "requirements.txt"
if errorlevel 1 goto :error
call :ensure_environment "IAM-ADSL" "flask, selenium, pdfplumber, iam_adsl" "requirements-dev.txt"
if errorlevel 1 goto :error
call :ensure_environment "IAM-Project" "flask, selenium, openpyxl, waitress" "requirements.txt"
if errorlevel 1 goto :error

echo.
echo ============================================================
echo   Starting Cuiver, FO and VULA on http://127.0.0.1:8080
echo ============================================================
echo.

set "PYTHONUNBUFFERED=1"
"%~dp0Project-IAM-FO-VULA\.venv\Scripts\python.exe" "%~dp0gateway.py"
set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" goto :error
exit /b 0

:select_python
where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_MODE=launcher"
    exit /b 0
)
where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_MODE=python"
    set "PYTHON_EXE=python"
    exit /b 0
)
if exist "%~dp0Project-IAM-FO-VULA\.venv\Scripts\python.exe" (
    set "PYTHON_MODE=python"
    set "PYTHON_EXE=%~dp0Project-IAM-FO-VULA\.venv\Scripts\python.exe"
    exit /b 0
)
echo ERROR: Python 3.10 or newer was not found.
exit /b 1

:ensure_environment
set "PROJECT_NAME=%~1"
set "IMPORT_NAMES=%~2"
set "REQUIREMENTS_FILE=%~3"
set "PROJECT_DIR=%~dp0%~1"
set "VENV_PYTHON=%~dp0%~1\.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo Creating the Python environment for %PROJECT_NAME%...
    if /i "%PYTHON_MODE%"=="launcher" (
        py -3 -m venv "%PROJECT_DIR%\.venv"
    ) else (
        "%PYTHON_EXE%" -m venv "%PROJECT_DIR%\.venv"
    )
    if errorlevel 1 exit /b 1
)

"%VENV_PYTHON%" -c "import %IMPORT_NAMES%" >nul 2>nul
if errorlevel 1 (
    echo Installing dependencies for %PROJECT_NAME%...
    pushd "%PROJECT_DIR%"
    "%VENV_PYTHON%" -m pip install -r "%REQUIREMENTS_FILE%"
    if errorlevel 1 (
        popd
        exit /b 1
    )
    popd
)
exit /b 0

:error
echo.
echo The FO portal could not be started. Review the error above.
pause
exit /b 1
