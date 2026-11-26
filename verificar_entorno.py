"""Verifica que la laptop está lista para AURA Vision.

    python verificar_entorno.py                    # revisa todo
    python verificar_entorno.py --descargar-modelos  # además descarga los modelos (hazlo con internet, antes de clase)
    python verificar_entorno.py --sin-camara       # no probar la cámara
"""

import argparse
import importlib
import os
import platform
import socket
import sys
import threading
import time


# Consolas de Windows que no usan UTF-8: evita que los emojis/tildes rompan la salida.
for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

OK, AVISO, ERROR = "✅", "⚠️ ", "❌"
resultados = []


def informe(estado, texto, ayuda=""):
    resultados.append(estado)
    print(f"{estado} {texto}" + (f"\n     → {ayuda}" if ayuda else ""))


def revisar_python():
    v = sys.version_info
    if v < (3, 9):
        informe(ERROR, f"Python {platform.python_version()} es muy antiguo", "Instala Python 3.11 desde python.org")
    elif v >= (3, 13):
        informe(AVISO, f"Python {platform.python_version()}: funciona, pero 3.10-3.12 es lo más probado en Windows")
    else:
        informe(OK, f"Python {platform.python_version()} ({platform.system()} {platform.machine()})")


def revisar_paquetes():
    faltan = []
    for mod, pip in [("numpy", "numpy"), ("scipy", "scipy"), ("pandas", "pandas"), ("matplotlib", "matplotlib"),
                     ("yaml", "pyyaml"), ("cv2", "opencv-python"), ("onnxruntime", "onnxruntime"),
                     ("rtmlib", "rtmlib"), ("fastapi", "fastapi"), ("uvicorn", "uvicorn[standard]"),
                     ("qrcode", "qrcode")]:
        try:
            m = importlib.import_module(mod)
            print(f"     {mod:12s} {getattr(m, '__version__', '')}")
        except Exception:
            faltan.append(pip)
    if faltan:
        informe(ERROR, "Faltan paquetes: " + ", ".join(faltan), "Ejecuta: pip install -r requirements.txt")
    else:
        informe(OK, "Paquetes de Python instalados")
    return not faltan


def revisar_onnx():
    import onnxruntime as ort
    prov = ort.get_available_providers()
    gpu = "CUDAExecutionProvider" in prov
    informe(OK, f"ONNX Runtime {ort.__version__}: " + ("GPU CUDA disponible" if gpu else "CPU (GPU opcional)"))


def revisar_modelos(descargar):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from aura.config import cargar_config
    from aura.vision.pose import DETECTORES, MODELOS_POSE, parametros_modo
    cfg = cargar_config()
    p = parametros_modo(cfg["pose"])
    cache = os.path.join(os.path.expanduser("~"), ".cache", "rtmlib", "hub", "checkpoints")
    necesarios = [os.path.basename(DETECTORES[p["detector"]][0]), os.path.basename(MODELOS_POSE[p["modelo_pose"]][0])]
    presentes = [n for n in necesarios if os.path.exists(os.path.join(cache, n.replace(".zip", ".onnx")))
                 or os.path.exists(os.path.join(cache, n))]
    if len(presentes) == len(necesarios):
        informe(OK, f"Modelos del modo '{p['modo']}' ya descargados ({p['detector']} + {p['modelo_pose']})")
    elif descargar:
        print("     Descargando modelos (~70 MB)...")
        from aura.vision.pose import EstimadorPose
        EstimadorPose(cfg["pose"])
        informe(OK, "Modelos descargados")
    else:
        informe(AVISO, f"Modelos del modo '{p['modo']}' aún no descargados",
                "Se bajan solos al iniciar (necesita internet) o ahora con: python verificar_entorno.py --descargar-modelos")
        return None
    from aura.vision.pose import EstimadorPose
    import numpy as np
    est = EstimadorPose(cfg["pose"])
    img = np.random.default_rng(0).integers(0, 255, (720, 1280, 3), dtype=np.uint8)
    caja = np.array([[500, 100, 760, 700]], float)
    est.detectar(img)
    est.pose(img, caja)
    t = time.time()
    for _ in range(5):
        est.detectar(img)
    t_det = (time.time() - t) / 5
    t = time.time()
    for _ in range(10):
        est.pose(img, caja)
    t_pose = (time.time() - t) / 10
    fps = 1.0 / (t_pose + t_det / est.detectar_cada + 0.008)
    estado = OK if fps >= 15 else AVISO
    informe(estado, f"Velocidad estimada ({p['modo']}, 1 persona): ~{fps:.0f} FPS "
            f"(detector {t_det * 1000:.0f} ms cada {est.detectar_cada} cuadros, pose {t_pose * 1000:.0f} ms)",
            "" if fps >= 15 else "Prueba: python app.py --modo lightweight")


def revisar_camara(indice):
    import cv2
    res = {}

    def probar():
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        cap = cv2.VideoCapture(indice, backend)
        ok, img = cap.read() if cap.isOpened() else (False, None)
        res["ok"], res["forma"] = ok, None if img is None else img.shape
        cap.release()
    h = threading.Thread(target=probar, daemon=True)
    h.start()
    h.join(8)
    if res.get("ok"):
        informe(OK, f"Cámara {indice}: imagen de {res['forma'][1]}×{res['forma'][0]}")
    else:
        informe(AVISO, f"No se pudo leer la cámara {indice}",
                "Cierra otras apps que la usen (Zoom, Teams), revisa permisos de cámara en Windows, prueba otro índice "
                "(--camara 1) o usa el modo demo: python app.py --demo video.mp4")


def revisar_red(puerto):
    with socket.socket() as s:
        try:
            s.bind(("0.0.0.0", puerto))
            informe(OK, f"Puerto {puerto} libre")
        except OSError:
            informe(AVISO, f"Puerto {puerto} ocupado", "La app usará el siguiente libre automáticamente")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from aura.ui.servidor import ip_local
    ip = ip_local()
    if ip.startswith("127."):
        informe(AVISO, "Sin red local: el celular no podrá abrir la app (la laptop sí)")
    else:
        informe(OK, f"IP en la red local: {ip} (el celular debe estar en la misma red Wi-Fi)",
                "Si el celular no carga la página: permite Python en el Firewall de Windows (redes privadas)")


def main():
    ap = argparse.ArgumentParser(description="Verifica el entorno de AURA Vision")
    ap.add_argument("--descargar-modelos", action="store_true")
    ap.add_argument("--sin-camara", action="store_true")
    ap.add_argument("--camara", type=int, default=0)
    args = ap.parse_args()
    print("\n=== AURA Vision · verificación del entorno ===\n")
    revisar_python()
    if revisar_paquetes():
        revisar_onnx()
        try:
            revisar_modelos(args.descargar_modelos)
        except Exception as e:
            informe(ERROR, f"No se pudieron cargar los modelos: {e}",
                    "Revisa la conexión a internet (download.openmmlab.com) y vuelve a intentarlo")
        if not args.sin_camara:
            revisar_camara(args.camara)
        revisar_red(8000)
    print()
    if ERROR in resultados:
        print("❌ Hay problemas que resolver antes de la demostración (ver arriba).")
        sys.exit(1)
    print("✅ Todo listo. Inicia con:  python app.py" + ("   (revisa los avisos ⚠️)" if AVISO in resultados else ""))


if __name__ == "__main__":
    main()
