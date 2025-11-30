@echo off
REM Fast-mode launcher for Memmert IPP30 simulator
REM Detect Python and run memmert_control_fast.py (targets http://127.0.0.1:8000/atmoweb)

echo Starting Memmert IPP30 FAST Control (simulator)
echo =============================================

setlocal ENABLEEXTENSIONS
set "SCRIPT_PATH=%~dp0memmert_control_fast.py"
set "SIMULATOR_PATH=%~dp0temp_chamber_sim.py"

REM Activate conda base environment to ensure numpy is available
call conda activate base >nul 2>nul

REM Allow override: set MEMMERT_PYTHON=C:\Path\to\python.exe
set "PYTHON_PATH=%MEMMERT_PYTHON%"
REM Try common Miniconda install locations automatically
if not defined PYTHON_PATH (
    if exist "%LocalAppData%\Programs\miniconda3\python.exe" set "PYTHON_PATH=%LocalAppData%\Programs\miniconda3\python.exe"
)
if not defined PYTHON_PATH (
    if exist "%UserProfile%\miniconda3\python.exe" set "PYTHON_PATH=%UserProfile%\miniconda3\python.exe"
)
REM Try common Python.org install locations
if not defined PYTHON_PATH (
    if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PYTHON_PATH=%LocalAppData%\Programs\Python\Python311\python.exe"
)
if not defined PYTHON_PATH (
    if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYTHON_PATH=%LocalAppData%\Programs\Python\Python312\python.exe"
)
if not defined PYTHON_PATH (
    if exist "C:\Program Files\Python311\python.exe" set "PYTHON_PATH=C:\Program Files\Python311\python.exe"
)
if not defined PYTHON_PATH (
    if exist "C:\Program Files\Python312\python.exe" set "PYTHON_PATH=C:\Program Files\Python312\python.exe"
)
if not defined PYTHON_PATH (
    where py >nul 2>nul && set "PYTHON_PATH=py" || (
        where python >nul 2>nul && set "PYTHON_PATH=python"
    )
)

if not defined PYTHON_PATH (
    echo ERROR: No Python interpreter found.
    echo - Try installing Python from python.org and ensure 'Add to PATH'.
    echo - Or run via Windows launcher by installing Python and using 'py'.
    echo - Or set MEMMERT_PYTHON to your python.exe path.
    echo Example: set MEMMERT_PYTHON=C:\Users\YourName\AppData\Local\Programs\Python\Python311\python.exe
    goto :wait_and_exit_9009
)

REM Check if simulator is already running on port 8000
echo Checking for simulator on port 8000...
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul 2>nul
if errorlevel 1 (
    echo Simulator not running. Starting simulator server at http://127.0.0.1:8000/atmoweb ...
    start "Memmert Simulator" "%PYTHON_PATH%" "%SIMULATOR_PATH%"
    REM Wait 2 seconds for simulator to start
    timeout /t 2 /nobreak >nul
) else (
    echo Simulator already running on port 8000. Reusing existing instance.
)

REM Run the fast controller
echo.
echo Starting fast controller...
"%PYTHON_PATH%" "%SCRIPT_PATH%"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo FAST Memmert control completed successfully
) else (
    echo.
    echo ERROR: FAST Memmert control failed with error code %ERRORLEVEL%
)

:wait_and_exit_9009
timeout /t 5 /nobreak
exit /b %ERRORLEVEL%
