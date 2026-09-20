@echo off
setlocal
cd /d "%~dp0"
set "APP=%~dp0Hera\Scripts\hera.py"
where pythonw >nul 2>&1
if %ERRORLEVEL%==0 (
  start "" pythonw "%APP%"
  exit /b 0
)
where python >nul 2>&1
if %ERRORLEVEL%==0 (
  python "%APP%"
  exit /b %ERRORLEVEL%
)
echo Python is not on PATH. Install Python 3 from python.org and check "Add python.exe to PATH".
pause
exit /b 1
