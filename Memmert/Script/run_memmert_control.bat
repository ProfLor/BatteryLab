@echo off
REM Batch file to control Memmert IPP30 from EC-LAB EXTAPP
REM Detect Python via Windows launcher 'py' or 'python', allow override

echo Starting Memmert IPP30 Control from EC-LAB
echo =============================================

REM Allow override: set MEMMERT_PYTHON=C:\Path\to\python.exe
setlocal ENABLEEXTENSIONS
set "SCRIPT_PATH=%~dp0memmert_control.py"

REM Determine Python executable
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

REM Execute the Python script
"%PYTHON_PATH%" "%SCRIPT_PATH%"

REM Check if execution was successful
if %ERRORLEVEL% EQU 0 (
    echo.
    echo Memmert control completed successfully
) else (
    echo.
    echo ERROR: Memmert control failed with error code %ERRORLEVEL%
)

:wait_and_exit_9009
REM Keep window open for 5 seconds to view output
timeout /t 5 /nobreak

exit /b %ERRORLEVEL%
