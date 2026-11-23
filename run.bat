@echo off
cd /d "%~dp0"

set "PYEXE="
if exist ".venv-gpu\Scripts\python.exe" set "PYEXE=.venv-gpu\Scripts\python.exe"
if not defined PYEXE if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"

if not defined PYEXE (
    echo Environment not found. Run setup.bat first.
    pause
    exit /b 1
)

"%PYEXE%" app.py
if errorlevel 1 pause
