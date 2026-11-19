@echo off
setlocal
echo RepoPilot v1.5.0 - Compatibility Windows Builder
echo Copyright (C) 2026 Mst. Choity Akter
cd /d "%~dp0"
py -3 --version >nul 2>&1 || (echo Python 3.11+ is required.& pause & exit /b 1)
py -3 -m pip install --upgrade pyinstaller
if errorlevel 1 (echo Could not install PyInstaller.& pause & exit /b 1)
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name RepoPilot repilot.py
if exist dist\RepoPilot.exe (
  echo Compatibility build complete: dist\RepoPilot.exe
  echo NOTE: This build is easier to inspect than the Nuitka release.
) else (
  echo Build failed. Review the messages above.
)
pause
