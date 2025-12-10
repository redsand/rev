@echo off
:: Wrapper script to run the PowerShell build script for rev

setlocal

echo =================================
echo   rev Build Script Wrapper
echo =================================
echo.

:: Check if PowerShell is available
where powershell >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: PowerShell is not available on this system.
    echo Please install PowerShell to use this build script.
    echo.
    pause
    exit /b 1
)

:: Run the PowerShell build script with all arguments passed through
powershell -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*

:: Check the exit code
if %errorlevel% neq 0 (
    echo.
    echo Build process failed with exit code %errorlevel%.
    pause
    exit /b %errorlevel%
)

echo.
echo Build process completed.
pause
