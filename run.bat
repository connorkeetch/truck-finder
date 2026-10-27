@echo off
rem MotorSift launcher for Windows. Double-click, or run from a terminal.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 launcher.py %*
) else (
    python launcher.py %*
)
if errorlevel 1 pause
