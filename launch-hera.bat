@echo off
setlocal
cd /d "%~dp0"
set "APP=%~dp0Hera\Scripts\hera.py"
set "LOG=%~dp0Hera\Data\hera_run.log"
set "PY=%LocalAppData%\Programs\Python\Python313\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%APP%" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo HERA exited with an error. Log: %LOG%
  pause
)
exit /b %ERRORLEVEL%
