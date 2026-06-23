@echo off
:: ─────────────────────────────────────────────────────────────────────────────
:: Celo Trader — Windows Desktop Launcher
:: Save this as "CeloTrader.bat" on your Desktop.
:: Double-click to launch the bot + dashboard.
:: ─────────────────────────────────────────────────────────────────────────────

:: Path to your project folder — EDIT THIS LINE
set PROJECT_DIR=%USERPROFILE%\celo_trader

:: Virtual environment paths
set PYTHON=%PROJECT_DIR%\venv\Scripts\python.exe
set STREAMLIT=%PROJECT_DIR%\venv\Scripts\streamlit.exe

echo ==============================================
echo   Celo Trader -- Starting Up
echo ==============================================

:: Check project folder exists
if not exist "%PROJECT_DIR%" (
    echo ERROR: Project folder not found at %PROJECT_DIR%
    echo Edit the PROJECT_DIR line in this file.
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"

:: Activate virtual environment
call "%PROJECT_DIR%\venv\Scripts\activate.bat"

:: Start trading bot in a separate window (so output is visible)
echo Starting trading bot...
start "CeloTrader Bot" cmd /k "%PYTHON% main.py --paper"

:: Wait for bot to initialise
timeout /t 3 /nobreak >nul

:: Start Streamlit dashboard
echo Launching dashboard...
start "CeloTrader Dashboard" cmd /k "%STREAMLIT% run dashboard.py --server.headless false --browser.gatherUsageStats false"

:: Wait for Streamlit to start
timeout /t 5 /nobreak >nul

:: Open browser
echo Opening browser...
start http://localhost:8501

echo.
echo   Dashboard: http://localhost:8501
echo   Bot log:   %PROJECT_DIR%\bot.log
echo.
echo   Close both terminal windows to stop the bot.
echo ==============================================
pause
