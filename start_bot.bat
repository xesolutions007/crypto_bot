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
    echo Created .env from .env.example. Add your API credentials locally if needed.
)

echo Starting local paper-trading dashboard...
echo Open http://127.0.0.1:8000 in your browser.
".venv\Scripts\python.exe" bot_master.py
goto :end

:error
echo Setup failed. Review the error above.
pause
exit /b 1

:end
endlocal
