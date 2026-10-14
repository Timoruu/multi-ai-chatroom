@echo off
setlocal
cd /d "%~dp0"

rem ---- locate a python interpreter -------------------------------------------
set "PY="

if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"

if not defined PY (
    if exist "%~dp0..\..\..\..\.workbuddy\binaries\python\envs\multiai\Scripts\python.exe" (
        set "PY=%~dp0..\..\..\..\.workbuddy\binaries\python\envs\multiai\Scripts\python.exe"
    )
)

if not defined PY (
    if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\multiai\Scripts\python.exe" (
        set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\multiai\Scripts\python.exe"
    )
)

if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)

if not defined PY (
    echo.
    echo   [ERROR] No Python interpreter found.
    echo   Install Python 3.10+ first, then run this file again.
    echo.
    pause
    exit /b 1
)

echo.
echo   Using Python: %PY%
echo   Installing dependencies into the current environment...
echo.

"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install fastapi "uvicorn[standard]" httpx

if errorlevel 1 (
    echo.
    echo   [ERROR] pip install failed. Check your network and try again.
    echo.
    pause
    exit /b 1
)

echo.
echo   Done. Now double-click start.bat
echo.
pause
endlocal
exit /b 0
