"""Descarga un video público de prueba TÉCNICA (peatones, de los ejemplos de OpenCV) y lo convierte a .mp4.

    python herramientas/descargar_video_prueba.py

Sirve para comprobar que la detección, el seguimiento y la interfaz funcionan sin cámara.
OJO: es una cámara elevada (no lateral), así que las alturas en metros y los estados no
son representativos. Para la demostración, graba tu propio video lateral con
``herramientas/grabar_video_demo.py``.
"""

import os
import urllib.request

import cv2

URL = "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/vtest.avi"


def main(destino="video_prueba.mp4"):
    tmp = destino + ".avi"
    print("Descargando", URL)
    urllib.request.urlretrieve(URL, tmp)
    cap = cv2.VideoCapture(tmp)
    fps = cap.get(cv2.CAP_PROP_FPS) or 10
    ok, img = cap.read()
    out = cv2.VideoWriter(destino, cv2.VideoWriter_fourcc(*"mp4v"), fps, (img.shape[1], img.shape[0]))
    while ok:
        out.write(img)
        ok, img = cap.read()
    out.release()
    cap.release()
    os.remove(tmp)
    print(f"Listo: {destino}. Prueba: python app.py --demo {destino}")


if __name__ == "__main__":
    main()
