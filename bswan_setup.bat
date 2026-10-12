@echo off
REM ============================================================
REM  bswan_setup.bat — Windows Task Scheduler setup
REM  Run once as Administrator to register the 7am daily task
REM ============================================================

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "FETCHER=%SCRIPT_DIR%bswan_fetcher.py"
set "LOG=%SCRIPT_DIR%bswan_fetcher.log"

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║   Black Swan Daily Convergence Monitor — Windows Setup   ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

REM ── Find Python ──────────────────────────────────────────────
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install from https://python.org
    pause & exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do set PYVER=%%i
echo OK  Python: %PYVER%

REM ── Install deps ─────────────────────────────────────────────
echo.
echo Installing Python dependencies...
python -m pip install --upgrade requests yfinance schedule --quiet
echo OK  Dependencies installed

REM ── FRED key ─────────────────────────────────────────────────
echo.
echo ────────────────────────────────────────────────────────────
echo FRED API key (free): https://fred.stlouisfed.org/docs/api/api_key.html
echo.
set /p FRED_KEY="Paste your FRED API key (or press Enter to skip): "

if not "!FRED_KEY!"=="" (
    echo FRED_API_KEY=!FRED_KEY! > "%SCRIPT_DIR%.env"
    echo OK  FRED key saved to .env
) else (
    echo WARN: Skipped — FRED indicators will hold last saved values
)

REM ── Create wrapper bat that loads .env ────────────────────────
set "RUNNER=%SCRIPT_DIR%bswan_run.bat"
(
    echo @echo off
    echo for /f "tokens=1,2 delims==" %%%%i in ^('%SCRIPT_DIR%.env'^) do set "%%%%i=%%%%j"
    echo python "%FETCHER%" ^>^> "%LOG%" 2^>^&1
) > "%RUNNER%"

REM ── Register Task Scheduler job ──────────────────────────────
echo.
echo Registering Windows Task Scheduler job ^(07:00 Mon–Fri^)...

schtasks /delete /tn "BlackSwanMonitor" /f >nul 2>&1

schtasks /create ^
  /tn "BlackSwanMonitor" ^
  /tr "\"%RUNNER%\"" ^
  /sc WEEKLY ^
  /d MON,TUE,WED,THU,FRI ^
  /st 07:00 ^
  /ru "%USERNAME%" ^
  /f >nul

if %errorlevel% equ 0 (
    echo OK  Task registered: BlackSwanMonitor at 07:00 Mon–Fri
) else (
    echo ERROR registering task. Try running this script as Administrator.
)

REM ── Run once now ─────────────────────────────────────────────
echo.
set /p RUN_NOW="Run the fetcher now to generate today's data? [Y/n]: "
if /i "!RUN_NOW!"=="n" goto :done

echo Fetching...
if not "!FRED_KEY!"=="" (
    set FRED_API_KEY=!FRED_KEY!
)
python "%FETCHER%"

if exist "%SCRIPT_DIR%daily_readings.json" (
    echo.
    echo OK  daily_readings.json written
    echo     Open black_swan_dashboard.html in your browser
)

:done
echo.
echo ═══════════════════════════════════════════════════════════
echo   Setup complete. Dashboard refreshes at 07:00 Mon–Fri.
echo.
echo   Manual run:    python %FETCHER%
echo   View logs:     type %LOG%
echo ═══════════════════════════════════════════════════════════
echo.
pause
