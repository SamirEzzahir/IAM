@echo off
setlocal
cd /d "%~dp0"
echo This shares ALL portal services on your local network.
echo Use only a trusted private network. Do not forward this port to the Internet.
echo To share only the map, use Coverage-Map\start.bat instead.
set "GATEWAY_HOST=0.0.0.0"
call "%~dp0run.bat"
exit /b %errorlevel%
