@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run START.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install PyInstaller==6.13.0
if errorlevel 1 goto error
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name LocalShot launcher.py
if errorlevel 1 goto error
echo Ready: dist\LocalShot\LocalShot.exe
explorer dist\LocalShot
pause
exit /b 0
:error
echo Build failed. See the error above.
pause
exit /b 1
