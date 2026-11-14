@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment. Install Python 3.10+ first.
        pause
        exit /b 1
    )
)

echo Installing/updating required packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo Created .env from .env.example. Add API credentials locally if needed.
)

if not exist "certs\botstrategiesmodules.crt" (
    echo Creating a local HTTPS certificate...
    ".venv\Scripts\python.exe" generate_local_cert.py
    if errorlevel 1 goto :error
)

echo.
echo Dashboard address: https://botstrategiesmodules:8000/
echo If this is the first run, follow the README instructions to:
echo 1. Add 127.0.0.1 botstrategiesmodules to the Windows hosts file.
echo 2. Trust certs\botstrategiesmodules.crt in Windows Trusted Root Certification Authorities.
echo.
echo Starting local paper-trading dashboard...
".venv\Scripts\python.exe" -m uvicorn bot_master:app --host 127.0.0.1 --port 8000 --ssl-keyfile certs\botstrategiesmodules.key --ssl-certfile certs\botstrategiesmodules.crt
goto :end

:error
echo Setup failed. Review the error above.
pause
exit /b 1

:end
endlocal
