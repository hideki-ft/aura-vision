@echo off
chcp 65001 >nul
title AURA Vision - modo demo
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Primero ejecuta instalar.bat
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
if exist "demo.mp4" (
  echo Modo demo con el video demo.mp4
  python app.py --demo demo.mp4 %*
) else (
  echo No hay demo.mp4 en esta carpeta: uso la persona sintética.
  echo Para grabar tu video de respaldo:  python herramientas\grabar_video_demo.py --salida demo.mp4
  python app.py --sintetico %*
)
pause
