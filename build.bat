@echo off
REM ============================================================
REM  Shade Engine - one-click Windows build
REM  Produces a single file:  dist\Shade Engine.exe
REM  Requires: Windows + Python 3.10+ (add to PATH during install)
REM ============================================================
setlocal
title Shade Engine - Build

echo.
echo  ============================================
echo    Shade Engine - Windows build
echo  ============================================
echo.

REM --- pick a working python launcher ---
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if "%PY%"=="" (
  python --version >nul 2>&1 && set "PY=python"
)
if "%PY%"=="" (
  echo [ERROR] Python was not found. Install Python 3.10+ from https://python.org
  echo         and tick "Add Python to PATH" during setup, then run build.bat again.
  pause
  exit /b 1
)
echo [1/3] Using Python: %PY%

echo [2/3] Installing / updating dependencies...
%PY% -m pip install --upgrade pip >nul
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Failed to install dependencies. Check your internet connection.
  pause
  exit /b 1
)

echo [3/3] Building the executable with PyInstaller...
%PY% -m PyInstaller --noconfirm --clean ShadeEngine.spec
if errorlevel 1 (
  echo [ERROR] Build failed. Scroll up to see the PyInstaller error.
  pause
  exit /b 1
)

echo.
echo  ============================================
echo    DONE!  Your app is here:
echo      dist\Shade Engine.exe
echo.
echo    It is a SINGLE self-contained file.
echo    Right-click it - Run as administrator.
echo  ============================================
echo.
pause
