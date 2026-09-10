@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" goto run
where py >nul 2>nul
if errorlevel 1 goto no_python
py -3 -m venv .venv
if errorlevel 1 goto error
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto error
:run
.venv\Scripts\python.exe -c "import PySide6, PIL" >nul 2>nul
if errorlevel 1 goto repair
start "" ".venv\Scripts\pythonw.exe" app.py
exit /b 0
:repair
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto error
goto run
:no_python
echo Install Python 3.11 or 3.12 from python.org with Python Launcher enabled.
pause
exit /b 1
:error
echo Setup failed. Check the error above and internet connection.
pause
exit /b 1
