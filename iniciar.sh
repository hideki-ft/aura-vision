#!/usr/bin/env bash
# AURA Vision - iniciar en Linux / macOS. Acepta las mismas opciones que app.py (--demo, --sintetico, ...)
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Primero ejecuta ./instalar.sh"; exit 1; }
. .venv/bin/activate
exec python app.py "$@"
