@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo RepoPilot v1.5.0 - Hardened Windows Release Builder
echo Copyright (C) 2026 Mst. Choity Akter
echo ============================================================
echo.
py -3 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3 is required. Install Python 3.11+ from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
echo Installing Nuitka build tools...
py -3 -m pip install --upgrade nuitka ordered-set zstandard
if errorlevel 1 (
  echo Could not install Nuitka build tools.
  pause
  exit /b 1
)
if not exist dist mkdir dist
echo.
echo Compiling RepoPilot to a native Windows executable.
echo The first build may download a C compiler and can take several minutes.
echo.
py -3 -m nuitka --onefile --windows-console-mode=disable --enable-plugin=tk-inter --assume-yes-for-downloads --mingw64 --output-dir=dist --output-filename=RepoPilot.exe --company-name="Mst. Choity Akter" --product-name="RepoPilot" --file-version=1.5.0.0 --product-version=1.5.0.0 --file-description="RepoPilot GitHub Multi-Account Uploader" --copyright="Copyright (C) 2026 Mst. Choity Akter. All rights reserved." repilot.py
if errorlevel 1 (
  echo.
  echo Hardened Nuitka build failed. Review the error above.
  echo You may use BUILD-WINDOWS-COMPATIBLE.bat as a compatibility build,
  echo but that PyInstaller build is easier to inspect and is not the hardened release.
  pause
  exit /b 1
)
if exist dist\RepoPilot.exe (
  echo.
  echo Build complete: dist\RepoPilot.exe
  echo Distribute the EXE only. Do NOT distribute this source ZIP if you want to keep source private.
  echo For publisher verification, sign the EXE with your own Authenticode certificate.
) else (
  echo Build finished but dist\RepoPilot.exe was not found.
)
pause
