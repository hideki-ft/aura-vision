"""Graba un video de respaldo con la cámara de la laptop para el modo demo.

    python herramientas/grabar_video_demo.py --salida demo.mp4 --segundos 60

Pulsa ESPACIO para empezar/pausar y Q para terminar. Graba de lado (vista lateral),
cuerpo completo, buena luz. Si simulas caídas, usa un colchón. Pide consentimiento
a quien aparezca en el video.
"""

import argparse
import time

import cv2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camara", type=int, default=0)
    ap.add_argument("--salida", default="demo.mp4")
    ap.add_argument("--segundos", type=float, default=120)
    ap.add_argument("--fps", type=float, default=30)
    a = ap.parse_args()
    cap = cv2.VideoCapture(a.camara)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    ok, img = cap.read()
    if not ok:
        raise SystemExit("No se pudo abrir la cámara")
    h, w = img.shape[:2]
    out = cv2.VideoWriter(a.salida, cv2.VideoWriter_fourcc(*"mp4v"), a.fps, (w, h))
    grabando, t0, n = False, None, 0
    print("ESPACIO = grabar/pausar · Q = terminar")
    while True:
        ok, img = cap.read()
        if not ok:
            break
        if grabando:
            out.write(img)
            n += 1
        vista = img.copy()
        cv2.putText(vista, "GRABANDO" if grabando else "PAUSA (ESPACIO para grabar)", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255) if grabando else (255, 255, 255), 2)
        cv2.imshow("AURA - grabar video demo", vista)
        k = cv2.waitKey(1) & 0xFF
        if k == ord(" "):
            grabando = not grabando
            t0 = t0 or time.time()
        if k == ord("q") or (t0 and time.time() - t0 > a.segundos):
            break
    out.release()
    cap.release()
    cv2.destroyAllWindows()
    print(f"Guardado {a.salida} ({n} cuadros). Prueba: python app.py --demo {a.salida}")


if __name__ == "__main__":
    main()
