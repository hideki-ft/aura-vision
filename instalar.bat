@echo off
chcp 65001 >nul
title AURA Vision - instalación
cd /d "%~dp0"
echo ============================================================
echo   AURA Vision - instalación (solo la primera vez)
echo ============================================================
set "PY="
py -3.11 --version >nul 2>&1 && set "PY=py -3.11" && goto :tengo_python
py -3 --version >nul 2>&1 && set "PY=py -3" && goto :tengo_python
python --version >nul 2>&1 && set "PY=python" && goto :tengo_python
echo.
echo [X] No encontré Python. Instala Python 3.11 desde https://www.python.org/downloads/
echo     y marca la casilla "Add python.exe to PATH". Luego vuelve a ejecutar este archivo.
pause
exit /b 1
:tengo_python
echo Usando: %PY%
if not exist ".venv\Scripts\python.exe" (
  echo Creando el entorno virtual .venv ...
  %PY% -m venv .venv || (echo [X] No se pudo crear el entorno virtual & pause & exit /b 1)
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || (echo [X] Falló la instalación de paquetes. Revisa tu conexión a internet. & pause & exit /b 1)
echo.
echo Descargando modelos y verificando el entorno...
python verificar_entorno.py --descargar-modelos
echo.
echo ============================================================
echo   Listo. Para iniciar: doble clic en iniciar.bat
echo   (o iniciar_demo.bat para el modo demo sin cámara)
echo ============================================================
pause
