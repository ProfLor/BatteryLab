@echo off
REM Batch file to control Memmert IPP30 from EC-LAB EXTAPP
REM This batch file calls the Python script to control the incubator

echo Starting Memmert IPP30 Control from EC-LAB
echo =============================================

REM Set the path to your Python installation (use 'python' if in PATH)
set PYTHON_PATH=python

REM Set the path to the control script
set SCRIPT_PATH=%~dp0memmert_control.py

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

REM Keep window open for 5 seconds to view output
timeout /t 5 /nobreak

exit /b %ERRORLEVEL%
