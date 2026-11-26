"""AURA Vision · inicia la aplicación.

    python app.py                      # cámara 0
    python app.py --camara 1           # otra cámara
    python app.py --demo video.mp4     # modo demo con un video pregrabado
    python app.py --sintetico          # sin cámara ni modelos: persona sintética
    python app.py --modo lightweight   # laptop lenta

Abre sola la página en el navegador y muestra la IP y un código QR para el celular.
"""

import argparse
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser


# Consolas de Windows que no usan UTF-8: evita que los emojis/tildes rompan la salida.
for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from aura.config import cargar_config


def puerto_libre(inicial, host):
    for p in range(inicial, inicial + 20):
        with socket.socket() as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    raise RuntimeError("No hay puertos libres entre %d y %d" % (inicial, inicial + 19))


def main(argv=None):
    ap = argparse.ArgumentParser(description="AURA · Visión + Wi-Fi virtual")
    ap.add_argument("--config", default=None, help="archivo YAML con cambios sobre config.yaml")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--camara", type=int, default=None, help="índice de la cámara (0, 1, ...)")
    g.add_argument("--demo", default=None, metavar="VIDEO.mp4", help="usar un video pregrabado en vez de la cámara")
    g.add_argument("--sintetico", action="store_true", help="persona sintética (sin cámara ni modelos)")
    ap.add_argument("--modo", choices=["lightweight", "balanced", "performance"], default=None)
    ap.add_argument("--estatura", type=float, default=None, help="estatura de la persona en metros")
    ap.add_argument("--puerto", type=int, default=None)
    ap.add_argument("--solo-local", action="store_true", help="no permitir abrir la app desde el celular")
    ap.add_argument("--no-navegador", action="store_true", help="no abrir el navegador automáticamente")
    ap.add_argument("--segundos", type=float, default=None, help="cerrar sola tras N segundos (pruebas)")
    args = ap.parse_args(argv)

    cfg = cargar_config(args.config)
    if args.modo:
        cfg["pose"]["modo"] = args.modo
    if args.estatura:
        cfg["persona"]["estatura_m"] = args.estatura
    if args.sintetico:
        fuente = {"tipo": "sintetico"}
    elif args.demo or cfg["fuente"].get("video_demo"):
        ruta = args.demo or cfg["fuente"]["video_demo"]
        if not os.path.exists(ruta):
            sys.exit(f"No existe el video {ruta}")
        fuente = {"tipo": "video", "valor": ruta}
    else:
        fuente = {"tipo": "camara", "valor": cfg["fuente"]["camara"] if args.camara is None else args.camara}

    from aura.motor import Motor
    from aura.ui.servidor import crear_app, ip_local, qr_terminal

    motor = Motor(cfg, fuente)
    try:
        motor.iniciar()
    except Exception as e:
        print(f"\n❌ No se pudo iniciar la fuente de video: {e}")
        print("   Prueba:  python app.py --demo tu_video.mp4   o   python app.py --sintetico")
        sys.exit(1)

    red = cfg["interfaz"]["permitir_red_local"] and not args.solo_local
    host = "0.0.0.0" if red else "127.0.0.1"
    puerto = puerto_libre(args.puerto or int(cfg["interfaz"]["puerto"]), host)
    token = secrets.token_urlsafe(6)
    url_local = f"http://127.0.0.1:{puerto}/?t={token}"
    url_red = f"http://{ip_local()}:{puerto}/?t={token}" if red else None
    app = crear_app(motor, token, url_red)

    print("\n" + "=" * 64)
    print("  AURA · Visión + Wi-Fi virtual")
    print(f"  Fuente: {motor.fuente.descripcion}")
    print(f"  En esta laptop:  {url_local}")
    if url_red:
        print(f"  En el celular (misma red Wi-Fi):  {url_red}")
        print(qr_terminal(url_red))
    print("  Ctrl+C para salir (si estás grabando, se genera el reporte).")
    print("=" * 64 + "\n")

    if not args.no_navegador and cfg["interfaz"]["abrir_navegador"]:
        threading.Timer(1.5, lambda: webbrowser.open(url_local)).start()

    import uvicorn
    servidor = uvicorn.Server(uvicorn.Config(app, host=host, port=puerto, log_level="warning"))
    if args.segundos:
        def parar():
            time.sleep(args.segundos)
            servidor.should_exit = True
        threading.Thread(target=parar, daemon=True).start()
    try:
        servidor.run()
    finally:
        reporte = motor.detener()
        if reporte:
            print(f"📄 Reporte de la sesión: {reporte}")
        print("AURA cerrada.")


if __name__ == "__main__":
    main()
