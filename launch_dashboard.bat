@echo off
chcp 65001 >nul
setlocal

set PYTHON=
for /f "delims=" %%i in ('where python 2^>nul') do (
    if not defined PYTHON set PYTHON=%%i
)
if not defined PYTHON (
    echo [ERROR] python 인터프리터를 찾을 수 없습니다.
    pause
    exit /b 1
)

cd /d "%~dp0"
set PYTHONPATH=%~dp0src;%PYTHONPATH%
"%PYTHON%" -m streamlit run dashboard_app\app.py

endlocal
