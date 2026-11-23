@echo off
setlocal
cd /d "%~dp0"

echo.
echo === Speaker Splitter: setup ===
echo.

rem --- 1. Find Python 3.10-3.12 ---
set "PY="
for %%V in (3.12 3.11 3.10) do (
    if not defined PY (
        py -%%V --version >nul 2>&1 && set "PY=py -%%V"
    )
)
if defined PY goto :python_ok
python -c "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto :python_ok
echo ERROR: Python 3.10, 3.11 or 3.12 was not found.
echo Install it, for example: winget install -e --id Python.Python.3.12
echo Then open a new terminal and run setup.bat again.
goto :fail

:python_ok
echo Using Python: %PY%

rem --- 2. Check FFmpeg (shared build is required) ---
where ffmpeg >nul 2>&1
if errorlevel 1 goto :no_ffmpeg
ffmpeg -version 2>&1 | findstr /c:"--enable-shared" >nul
if errorlevel 1 goto :ffmpeg_not_shared
goto :ffmpeg_ok

:no_ffmpeg
echo.
echo WARNING: ffmpeg was not found.
echo Install it: winget install -e --id Gyan.FFmpeg.Shared
echo Then open a NEW terminal.
goto :ffmpeg_ok

:ffmpeg_not_shared
echo.
echo WARNING: ffmpeg is installed, but it is not the shared build.
echo Install the shared build: winget install -e --id Gyan.FFmpeg.Shared
echo Then open a NEW terminal.

:ffmpeg_ok

rem --- 3. Detect NVIDIA GPU ---
set "HASGPU="
nvidia-smi >nul 2>&1 && set "HASGPU=1"
if not defined HASGPU goto :cpu
set "ANS=Y"
set /p "ANS=NVIDIA GPU detected. Install the GPU version? [Y/n]: "
if /i "%ANS%"=="n" goto :cpu
goto :gpu

:cpu
set "VENV=.venv"
set "REQ=requirements.txt"
echo Installing the CPU version into %VENV%
goto :install

:gpu
set "VENV=.venv-gpu"
set "REQ=requirements-gpu.txt"
echo Installing the GPU version into %VENV%
goto :install

:install
%PY% -m venv %VENV%
if errorlevel 1 goto :fail
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install -r %REQ%
if errorlevel 1 goto :fail

rem --- 4. Create .env ---
if exist ".env" goto :env_ok
copy ".env.example" ".env" >nul
echo.
echo Created .env - paste your Hugging Face read token into it, then save and close Notepad.
notepad ".env"

:env_ok
echo.
echo Setup finished. Start the app with run.bat
pause
exit /b 0

:fail
echo.
echo Setup failed. See the messages above.
pause
exit /b 1
