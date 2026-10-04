@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call run.bat
".venv\Scripts\python.exe" -m pip install pyinstaller
".venv\Scripts\pyinstaller.exe" --noconfirm --onedir --windowed --name ArmorLab --collect-all panda3d --collect-all direct main.py
echo Done: dist\ArmorLab\ArmorLab.exe (the scenes and reports folders appear next to it when you save)
pause
