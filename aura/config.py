"""Carga de la configuración (config.yaml) con valores por defecto."""

import copy
import os

import yaml

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_POR_DEFECTO = os.path.join(RAIZ, "config.yaml")


def _fusionar(base, cambios):
    """Fusiona diccionarios de forma recursiva (``cambios`` gana)."""
    out = copy.deepcopy(base)
    for k, v in (cambios or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _fusionar(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def cargar_config(ruta=None, cambios=None):
    """Lee ``config.yaml`` (el del repositorio por defecto) y aplica ``cambios`` encima.

    Si se pasa otra ruta, sus valores se fusionan sobre los del config.yaml del
    repositorio, así un archivo propio puede contener solo lo que cambia.
    """
    with open(RUTA_POR_DEFECTO, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if ruta and os.path.abspath(ruta) != RUTA_POR_DEFECTO:
        with open(ruta, encoding="utf-8") as f:
            cfg = _fusionar(cfg, yaml.safe_load(f) or {})
    if cambios:
        cfg = _fusionar(cfg, cambios)
    return cfg
