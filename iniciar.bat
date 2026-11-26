@echo off
chcp 65001 >nul
title AURA Vision
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Primero ejecuta instalar.bat
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
python app.py %*
pause
