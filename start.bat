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

if not defined PY goto no_python

rem ---- check dependencies ----------------------------------------------------
"%PY%" -c "import fastapi, uvicorn, httpx" >nul 2>nul
if errorlevel 1 goto no_deps

if not defined PORT set "PORT=8765"
if not defined HOST set "HOST=127.0.0.1"

echo.
echo   Multi-model chatroom  ^>^>  http://%HOST%:%PORT%/
echo   Press Ctrl+C in this window to stop the server.
echo.
echo   Python: %PY%
echo.

"%PY%" run.py
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo   [ERROR] Server exited with code %RC%. See the messages above.
    echo.
    pause
)

endlocal
exit /b %RC%

rem ---- error paths -----------------------------------------------------------
:no_python
echo.
echo   [ERROR] No Python interpreter found.
echo   Run install_deps.bat once, then start again.
echo.
pause
endlocal
exit /b 1

:no_deps
echo.
echo   [ERROR] Missing dependencies: fastapi / uvicorn / httpx
echo   Run install_deps.bat once, then start again.
echo.
pause
endlocal
exit /b 1
