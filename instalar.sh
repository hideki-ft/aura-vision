#!/usr/bin/env bash
# AURA Vision - instalación en Linux / macOS (solo la primera vez)
set -e
cd "$(dirname "$0")"
PY=$(command -v python3.11 || command -v python3)
[ -x .venv/bin/python ] || "$PY" -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python verificar_entorno.py --descargar-modelos
echo "Listo. Inicia con: ./iniciar.sh   (o ./iniciar.sh --sintetico)"
