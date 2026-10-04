@echo off
cd /d "%~dp0"
set "PY="
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY if exist "C:\Python314\python.exe" set "PY=C:\Python314\python.exe"
if not defined PY if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if not defined PY goto nopython
echo Using: %PY%
if exist ".venv\Scripts\python.exe" goto run
echo First run: creating the environment and installing Panda3D and NumPy (one time only)...
%PY% -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
:run
".venv\Scripts\python.exe" main.py
echo.
echo Program finished with exit code %errorlevel%.
pause
goto end
:nopython
echo Python not found. Install Python 3.12 from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH", then run run.bat again.
pause
goto end
:fail
echo Failed to create the environment or install dependencies (see messages above).
echo If installing Panda3D failed, install Python 3.12 alongside, delete the .venv folder and run again.
pause
:end
