"""Prepara los datos de la versión web (GitHub Pages) a partir del código Python.

    python herramientas/exportar_web.py

* web/datos/config.json         ← config.yaml (mismos umbrales que la app de escritorio)
* aura/ui/static/marioneta.js     ← copia de web/js/marioneta.js (la persona controlable, para la app de escritorio)
* web/tests/casos.json           ← casos de prueba para comprobar que el JavaScript da lo mismo que Python
* web/js/dibujo.js               ← los 6 paneles, copiados de aura/ui/static/app.js (mismo dibujo en ambas versiones)
"""

import json
import os
import sys

import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from aura.config import cargar_config  # noqa: E402
from aura.sintetico import Escena, a_pixeles  # noqa: E402


def _guardar(ruta, datos):
    with open(os.path.join(RAIZ, ruta), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    print("escrito", ruta)


def secuencia(esc, ruido=1.0, semilla=0):
    T, K, C, B = a_pixeles(esc, ruido_px=ruido, semilla=semilla)
    return {"fps": esc.fps, "t": np.round(T, 4).tolist(), "kps": np.round(K, 2).tolist(),
            "scores": np.round(C, 3).tolist(), "cajas": np.round(B, 1).tolist()}


def exportar_dibujo():
    """Extrae de app.js las funciones de dibujo y las envuelve como módulo ES para la versión web."""
    with open(os.path.join(RAIZ, "aura/ui/static/app.js"), encoding="utf-8") as f:
        lineas = f.read().split("\n")
    ini = next(i for i, l in enumerate(lineas) if l.startswith("const COLORES"))
    fin_const = next(i for i, l in enumerate(lineas) if l.startswith("let estado"))
    dib = next(i for i, l in enumerate(lineas) if "utilidades de dibujo" in l)
    ctrl = next(i for i, l in enumerate(lineas) if "-- controles" in l)
    cuerpo = "\n".join(lineas[ini:fin_const]) + "\n" + "\n".join(lineas[dib:ctrl])
    js = ("// GENERADO por herramientas/exportar_web.py a partir de aura/ui/static/app.js — no editar a mano.\n"
          "/* eslint-disable */\n"
          "const TOKEN = \"\";\nlet estado = null;\nlet imagen = null;\nexport const medidoHist = [];\n"
          + cuerpo +
          "\nexport function fijarEstado(e, img) { estado = e; imagen = img; }\n"
          "export { dibujarTodo, COLORES, NOMBRES };\n")
    with open(os.path.join(RAIZ, "web/js/dibujo.js"), "w", encoding="utf-8") as f:
        f.write(js)
    print("escrito web/js/dibujo.js")


def main():
    exportar_dibujo()
    cfg = cargar_config()
    _guardar("web/datos/config.json", cfg)
    import shutil
    shutil.copyfile(os.path.join(RAIZ, "web/js/marioneta.js"), os.path.join(RAIZ, "aura/ui/static/marioneta.js"))
    print("copiado web/js/marioneta.js -> aura/ui/static/marioneta.js")
    # Casos para comparar JavaScript con Python
    from aura.vision.clasificador import ClasificadorEstados
    from aura.vision.one_euro import OneEuroFilter
    from aura.wifi_virtual.canal import CanalWifi
    from aura.wifi_virtual.metricas import espectro
    casos = {"clasificador": {}, "canal": {}, "welch": {}}
    for nombre, esc in [("caida", Escena().de_pie(3).caer().tumbado(33)),
                        ("caminata", Escena(x0=0.4).de_pie(1).caminar(4).de_pie(1.5)),
                        ("salto", Escena().de_pie(2).saltar().de_pie(2))]:
        s = secuencia(esc)
        cl = ClasificadorEstados(cfg["clasificacion"], cfg["alertas"], 1.70)
        f = OneEuroFilter(**cfg["one_euro"])
        estados, eventos, alertas = [], [], []
        for t, k, c, b in zip(s["t"], s["kps"], s["scores"], s["cajas"]):
            o = cl.actualizar(t, f(np.array(k), t), np.array(c), np.array(b))
            estados.append(o["estado"])
            eventos += [e["tipo"] for e in o.get("eventos") or []]
            alertas += [a["mensaje"] for a in o.get("alertas") or []]
        casos["clasificador"][nombre] = dict(s, estados=estados, eventos=eventos, alertas=alertas,
                                             ultimo_salto=cl.ultimo_salto)
    c = CanalWifi(cfg["wifi"])
    P = [[1.0, 0.5], [1.0, 1.5], [2.3, 2.1], [0.6, 0.4]]
    H = c.H(np.array(P))
    casos["canal"] = {"P": P, "absH": np.abs(H).round(8).tolist(), "argH": np.angle(H).round(8).tolist(),
                      "absH_vacia": np.abs(c.H_vacia()).round(8).tolist()}
    rng = np.random.default_rng(3)
    A = (1 + 0.1 * np.sin(2 * np.pi * 7.3 * np.arange(400) / 100)[:, None] + 0.02 * rng.standard_normal((400, 26)))
    fw, Pw = espectro(A, 100, 128)
    casos["welch"] = {"A": A.round(8).tolist(), "f": fw.tolist(), "P": Pw.tolist()}
    _guardar("web/tests/casos.json", casos)


if __name__ == "__main__":
    main()
