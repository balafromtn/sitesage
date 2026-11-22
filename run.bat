@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

:: Navigate to script directory
cd /d "%~dp0"

echo ======================================================================
echo                     SiteSage - One-Click Launcher
echo ======================================================================
echo.

set "VENV_DIR=venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_ACTIVATE=%VENV_DIR%\Scripts\activate.bat"

:: 1. If virtual environment already exists, use it directly
if exist "%VENV_PYTHON%" if exist "%VENV_ACTIVATE%" (
    echo [OK] Virtual environment '%VENV_DIR%' found.
    goto activate_env
)

:: 2. Find a working Python installation to create venv
echo [*] Virtual environment '%VENV_DIR%' not found. Searching for Python...
set "SYS_PYTHON="

:: Check if standard 'python' command works (and is not WindowsApps stub)
python -c "import sys" >nul 2>&1
if %errorlevel% equ 0 (
    set "SYS_PYTHON=python"
    goto create_env
)

:: Check if 'py -3' works
py -3 -c "import sys" >nul 2>&1
if %errorlevel% equ 0 (
    set "SYS_PYTHON=py -3"
    goto create_env
)

:: Search PATH entries for real python.exe (skipping WindowsApps)
for /f "tokens=*" %%p in ('where python 2^>nul') do (
    echo %%p | findstr /i /c:"WindowsApps" >nul
    if errorlevel 1 (
        "%%p" -c "import sys" >nul 2>&1
        if !errorlevel! equ 0 (
            set "SYS_PYTHON=%%p"
            goto create_env
        )
    )
)

:: Check common Windows Python install locations
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*" "%LOCALAPPDATA%\Python\pythoncore-*" "%ProgramFiles%\Python3*") do (
    if exist "%%D\python.exe" (
        "%%D\python.exe" -c "import sys" >nul 2>&1
        if !errorlevel! equ 0 (
            set "SYS_PYTHON=%%D\python.exe"
            goto create_env
        )
    )
)

if "%SYS_PYTHON%"=="" (
    echo [ERROR] No working Python 3.10+ installation could be found.
    echo Please install Python 3.10 or higher from https://www.python.org/
    echo During installation, be sure to check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

:create_env
for /f "tokens=2 delims= " %%v in ('%SYS_PYTHON% --version 2^>^&1') do set "PY_VER=%%v"
echo [OK] Found Python %PY_VER% (%SYS_PYTHON%)

%SYS_PYTHON% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] SiteSage requires Python 3.10 or higher.
    echo Current installed version is %PY_VER%. Please upgrade Python.
    echo.
    pause
    exit /b 1
)

echo [*] Creating virtual environment in '%VENV_DIR%'...
%SYS_PYTHON% -m venv %VENV_DIR%
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create virtual environment '%VENV_DIR%'.
    pause
    exit /b 1
)
echo [OK] Virtual environment created successfully.

:activate_env
echo [*] Activating virtual environment...
call "%VENV_ACTIVATE%"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)
echo [OK] Virtual environment active.

:: 3. Ensure .env exists
if not exist ".env" (
    if exist ".env.example" (
        echo [*] Initializing .env configuration from .env.example...
        copy ".env.example" ".env" >nul
        echo [OK] Created .env configuration file.
    )
)

:: 4. Check & Install Dependencies
echo [*] Checking and verifying dependencies from requirements.txt...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install required packages from requirements.txt.
    echo Please check your internet connection or C++ build tools if compiling wheels.
    echo.
    pause
    exit /b 1
)
echo [OK] All dependencies installed and up to date.

:: 5. Optional Gemini API Key Configuration
echo.
echo [*] Checking AI polish configuration...

set "KEY_EXISTS=0"
python -c "import os, sys; from dotenv import load_dotenv; load_dotenv('.env'); k = (os.environ.get('GEMINI_API_KEY') or '').strip().lower(); sys.exit(0 if (k and not k.startswith('your_') and 'api_key' not in k and 'placeholder' not in k and len(k) >= 15) else 1)" >nul 2>&1
if !errorlevel! equ 0 (
    set "KEY_EXISTS=1"
    echo [OK] Gemini API key already configured in environment or .env.
    goto launch_app
)

echo [INFO] No valid Gemini API key configured.
echo.
echo ======================================================================
echo  Would you like to enable Gemini AI-enhanced responses?
echo   [1] Yes - Enter API key securely for this session
echo   [2] No  - Continue with 100%% deterministic evidence search
echo ======================================================================
echo.

:prompt_ai_choice
set "AI_CHOICE="
set /p "AI_CHOICE=Select an option [1=Yes, 2=No]: "
if "%AI_CHOICE%"=="1" goto prompt_key
if /i "%AI_CHOICE%"=="y" goto prompt_key
if /i "%AI_CHOICE%"=="yes" goto prompt_key
if "%AI_CHOICE%"=="2" goto skip_ai
if /i "%AI_CHOICE%"=="n" goto skip_ai
if /i "%AI_CHOICE%"=="no" goto skip_ai
echo [WARN] Please enter 1 (Yes) or 2 (No).
goto prompt_ai_choice

:prompt_key
echo.
echo [*] Please enter your Gemini API key below.
echo [*] Input is hidden for security (keystrokes will not be echoed).
set "TEMP_GEMINI_KEY="
for /f "usebackq delims=" %%k in (`powershell -NoProfile -Command "$s = Read-Host -Prompt 'Gemini API Key' -AsSecureString; if ($s) { [System.Runtime.InteropServices.Marshal]::PtrToStringAuto([System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)) }"`) do (
    set "TEMP_GEMINI_KEY=%%k"
)

if defined TEMP_GEMINI_KEY (
    for /f "tokens=* delims= " %%A in ("!TEMP_GEMINI_KEY!") do set "TEMP_GEMINI_KEY=%%A"
)

if not defined TEMP_GEMINI_KEY (
    echo.
    echo [WARN] No API key was provided.
    :empty_key_choice
    echo   [1] Retry entering API key
    echo   [2] Continue without AI enhancement
    set "EMPTY_CHOICE="
    set /p "EMPTY_CHOICE=Select an option [1=Retry, 2=Continue]: "
    if "!EMPTY_CHOICE!"=="1" goto prompt_key
    if "!EMPTY_CHOICE!"=="2" goto skip_ai
    echo [WARN] Please enter 1 or 2.
    goto empty_key_choice
)

set "GEMINI_API_KEY=!TEMP_GEMINI_KEY!"
set "AI_POLISH_ENABLED=true"
echo.
echo [OK] Gemini API key configured in memory for this session.
echo [NOTE] Key is kept in memory only and will not be written to .env, SQLite, or disk.
goto launch_app

:skip_ai
set "AI_POLISH_ENABLED=false"
echo.
echo [INFO] AI enhancement disabled. SiteSage will run in 100%% deterministic mode.
goto launch_app

:launch_app
:: 6. Launch Application
echo.
echo ======================================================================
echo  Starting SiteSage Application Server...
echo  Local URL:  http://127.0.0.1:8000
echo  Press Ctrl+C to terminate the server.
echo ======================================================================
echo.

python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
if %errorlevel% neq 0 (
    echo.
    echo [NOTICE] Application server stopped or encountered an error (exit code: %errorlevel%).
    echo If port 8000 is occupied, you can change the PORT in your .env file.
    echo.
    pause
)
