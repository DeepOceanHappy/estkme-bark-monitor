@echo off
setlocal
cd /d "%~dp0"

set "BUNDLED_PY=C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 server.py %*
  goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
  python server.py %*
  goto :end
)

if exist "%BUNDLED_PY%" (
  "%BUNDLED_PY%" server.py %*
  goto :end
)

echo Cannot find Python. Please install Python 3 or run this from Codex desktop.
pause

:end
endlocal
