"""La versión web usa los mismos parámetros que la app de escritorio."""
import json
import os

from aura.config import cargar_config

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_config_web_sincronizada():
    """Si cambias config.yaml, ejecuta: python herramientas/exportar_web.py"""
    with open(os.path.join(RAIZ, "web", "datos", "config.json"), encoding="utf-8") as f:
        web = json.load(f)
    assert web == json.loads(json.dumps(cargar_config())), "Ejecuta: python herramientas/exportar_web.py"


def test_modelos_web_presentes():
    for m in ("yolox_tiny.onnx", "rtmpose_s.onnx", "rtmpose_m.onnx"):
        assert os.path.getsize(os.path.join(RAIZ, "web", "modelos", m)) > 1e6
