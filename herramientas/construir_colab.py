"""Genera notebooks/aura_colab.ipynb (AURA en Google Colab con la cámara del navegador y la GPU de Colab).

    python herramientas/construir_colab.py
"""
import os

import nbformat as nbf

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
celdas = [
    md("""# 🎥 AURA en Google Colab — cámara en vivo con la GPU de Colab

Este notebook descarga AURA desde **GitHub** (`hideki-ft/aura-vision`) y lo ejecuta en la **GPU T4 de Colab**.
Tu navegador abre la cámara, envía cada cuadro a Colab, AURA lo procesa (el mismo motor que la app de escritorio:
pose RTMPose, seguimiento, reglas físicas y Wi-Fi virtual) y dibuja el resultado **encima del video en vivo**.

**Antes de empezar:** menú **Entorno de ejecución → Cambiar tipo de entorno de ejecución → GPU T4**, y luego ejecuta
las celdas en orden (▶️).

**Para que no salga "incierto":** la cámara tiene que ver **el cuerpo completo** (cabeza a pies). Aléjate 2-3 m de la
laptop o pon la cámara/celular de lado, a la altura de la cadera.

**Velocidad:** cada cuadro viaja por internet a Colab y vuelve. Con buena conexión se consiguen ~5-12 cuadros/s
(la GPU tarda pocos milisegundos; lo que limita es la red).

🔒 Los cuadros solo viajan entre tu navegador y tu máquina virtual de Colab y **no se guardan**; la sesión grabada
contiene solo números (estados, velocidades, V)."""),
    md("""## 1 · Descargar AURA desde GitHub e instalar

Clona el repositorio e instala **ONNX Runtime con GPU** y **rtmlib** (los modelos de pose). Tarda ~1 minuto."""),
    code("""import os, sys
if os.environ.get("AURA_REPO_LOCAL"):          # solo para pruebas automáticas del repositorio
    REPO = os.environ["AURA_REPO_LOCAL"]
else:
    REPO = "/content/aura-vision"
    if not os.path.isdir(REPO):
        !git clone -q --depth 1 https://github.com/hideki-ft/aura-vision {REPO}
    else:
        !git -C {REPO} pull -q
    %pip install -q onnxruntime-gpu tqdm
    %pip install -q --no-deps rtmlib
sys.path.insert(0, REPO); os.chdir(REPO)
import onnxruntime as ort
gpu = "CUDAExecutionProvider" in ort.get_available_providers()
print("✅ AURA descargado." , "GPU disponible ✅" if gpu else "⚠️ Sin GPU: Entorno de ejecución → Cambiar tipo → GPU T4 (funciona en CPU, más lento)")"""),
    md("""## 2 · Configurar y cargar los modelos

Escribe tu **estatura** (sirve para convertir píxeles a metros). Con GPU se usa el modo `performance`
(detector YOLOX-m + RTMPose-m); sin GPU, `lightweight`. La primera vez se descargan los modelos (~150 MB).

Opcional: `MODELO_3D = True` hace que el Wi-Fi virtual también "vea" las caídas (usa la altura del tronco)."""),
    code("""ESTATURA_M = 1.70  # @param {type:"number"}
BANDA_GHZ = "2.4"  # @param ["2.4", "5.18"]
MODELO_3D = False  # @param {type:"boolean"}

from aura.config import cargar_config
from aura.colab import SesionColab, camara_en_vivo
cfg = cargar_config(cambios={"pose": {"modo": "performance" if gpu else "lightweight"},
                             "wifi": {"banda_ghz": BANDA_GHZ, "altura_antenas_m": 1.0 if MODELO_3D else None}})
sesion = SesionColab(cfg, ESTATURA_M)
print(f"Modelos listos en: {sesion.dispositivo.upper()}")"""),
    md("""## 3 · 📷 Cámara en vivo

Al ejecutar, el navegador pide **permiso para la cámara**: acéptalo. Verás el video con el esqueleto, la etiqueta
(DE PIE, CAMINANDO, SENTADO, SALTANDO, EN EL SUELO, POSIBLE CAÍDA), la física de la cadera y la V(t) del Wi-Fi
virtual (CALCULADO). Pulsa **⏹ Detener** para terminar.

* `GRABAR = True` guarda la sesión segundo a segundo (solo números) y genera un reporte.
* `CAMARA_FRONTAL = False` usa la cámara trasera si abres Colab en el celular.
* Si va lento, baja `ANCHO` a 480.
* Si sale **incierto**, el panel dice por qué (normalmente: no se ven las piernas → aléjate).
* Para probar caídas, **simúlalas sobre un colchón**. Las alertas son de bienestar, no diagnósticos."""),
    code("""GRABAR = True  # @param {type:"boolean"}
CAMARA_FRONTAL = True  # @param {type:"boolean"}
ANCHO = 640  # @param [480, 640, 800] {type:"raw"}
DURACION_MAX_S = 600  # @param {type:"integer"}

if GRABAR:
    sesion.grabar(True)
prueba = os.environ.get("AURA_VIDEO_PRUEBA")   # solo para pruebas automáticas (sin navegador)
camara_en_vivo(sesion, duracion_max_s=8 if prueba else DURACION_MAX_S, ancho=ANCHO,
               camara_frontal=CAMARA_FRONTAL, fuente_prueba=prueba)
RES = sesion.grabar(False) if GRABAR else None"""),
    md("""## 4 · Resultados de la sesión

Muestra el reporte (V(t) calculada con los estados, tiempo en cada estado, caídas y alertas) y descarga
`sesion.csv` + `reporte.html`. El CSV servirá como etiquetas cuando se use una ESP32 real."""),
    code("""from IPython.display import HTML, display
import shutil
if RES and RES.get("reporte"):
    carpeta = os.path.dirname(RES["reporte"])
    display(HTML(open(RES["reporte"], encoding="utf-8").read()))
    zipf = shutil.make_archive("/tmp/aura_sesion", "zip", carpeta)
    if "google.colab" in sys.modules and not os.environ.get("AURA_VIDEO_PRUEBA"):
        from google.colab import files
        files.download(zipf)
    print("Sesión:", carpeta)
else:
    print("No se grabó la sesión (GRABAR = False).")"""),
    md("""## Consejos

* **Cuerpo completo** en la imagen, de lado, a 2-3 m, con buena luz y la cámara quieta.
* **Velocidad:** depende de tu conexión a internet (cada cuadro va y vuelve). Usa Wi-Fi, no datos móviles.
* **La versión de escritorio** (`python app.py` en tu laptop) sigue siendo la más fluida si la laptop es razonable;
  la **página web** (https://hideki-ft.github.io/aura-vision/) no necesita nada pero depende de la GPU del dispositivo.
* Más información y el código: https://github.com/hideki-ft/aura-vision"""),
]
nb = nbf.v4.new_notebook()
nb["cells"] = celdas
nb["metadata"] = {"accelerator": "GPU", "colab": {"provenance": [], "gpuType": "T4", "name": "aura_colab.ipynb"},
                  "kernelspec": {"display_name": "Python 3", "name": "python3"}, "language_info": {"name": "python"}}
destino = os.path.join(RAIZ, "notebooks", "aura_colab.ipynb")
nbf.write(nb, destino)
print("escrito", destino)
