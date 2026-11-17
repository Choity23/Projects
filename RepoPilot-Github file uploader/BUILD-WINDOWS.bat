@echo off
setlocal
py -3 --version >nul 2>&1 || (echo Python 3 is required. Install Python 3.11+ from python.org and enable Add to PATH.& pause & exit /b 1)
py -3 -m pip install --upgrade pyinstaller
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name RepoPilot repilot.py
if exist dist\RepoPilot.exe (
  echo.
  echo Build complete: dist\RepoPilot.exe
  echo Copy RepoPilot.exe anywhere to use it as a portable app.
) else (
  echo Build failed. Review the messages above.
)
pause
