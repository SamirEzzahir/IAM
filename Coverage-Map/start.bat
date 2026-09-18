@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" -c "import flask, waitress, openpyxl, defusedxml, shapely" >nul 2>nul
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" app.py --setup
if errorlevel 1 goto :error
set "COVERAGE_PREFIX="
if not defined COVERAGE_HOST set "COVERAGE_HOST=0.0.0.0"
if not defined COVERAGE_PORT set "COVERAGE_PORT=5060"
echo.
echo Open http://127.0.0.1:%COVERAGE_PORT%/ on this PC.
echo Share http://IP_DU_PC:%COVERAGE_PORT%/ on your private LAN.
echo Use ipconfig to find the server IPv4 address.
echo Administration: /admin - Ctrl+C to stop.
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto :error
exit /b 0
:error
echo Unable to start Couverture FTTH. Review the error above.
pause
exit /b 1
