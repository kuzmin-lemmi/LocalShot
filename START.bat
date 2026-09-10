@echo off
setlocal
cd /d "%~dp0"
set "REPAIR_ATTEMPTED=0"
if exist ".venv\Scripts\pythonw.exe" goto run
where py >nul 2>nul
if errorlevel 1 goto no_python
py -3.12 -m venv .venv
if errorlevel 1 py -3.11 -m venv .venv
if errorlevel 1 goto error
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto error
:run
.venv\Scripts\python.exe -c "from PySide6 import QtWidgets; from PIL import Image" >nul 2>nul
if errorlevel 1 goto repair
start "" ".venv\Scripts\pythonw.exe" launcher.py
exit /b 0
:repair
if "%REPAIR_ATTEMPTED%"=="1" goto error
set "REPAIR_ATTEMPTED=1"
.venv\Scripts\python.exe -m pip install --force-reinstall -r requirements.txt
if errorlevel 1 goto error
goto run
:no_python
echo Install Python 3.11 or 3.12 from python.org with Python Launcher enabled.
pause
exit /b 1
:error
echo Setup failed. Check the error above and internet connection.
echo App errors: %%LOCALAPPDATA%%\LocalShot\logs\localshot.log
pause
exit /b 1
