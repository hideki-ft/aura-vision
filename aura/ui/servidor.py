"""Servidor local FastAPI + WebSocket.

* ``/``            página principal (necesita el token ``?t=...``).
* ``/ws``          WebSocket: el servidor envía el estado (JSON) y el video (JPEG) ~15 veces/s.
* ``/api/comando`` órdenes de la interfaz (estatura, banda, contraste, grabar...).
* ``/api/medido``  subir el CSV real de la maqueta (cuerpo de la petición = archivo).
* ``/api/qr.svg``  código QR con la dirección para abrir la app en el celular.

El token aleatorio evita que otras personas de la misma red Wi-Fi vean la cámara.
"""

import asyncio
import io
import json
import os
import secrets
import socket

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

ESTATICOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def ip_local():
    """IP de esta laptop en la red local (no envía datos: solo consulta la ruta del sistema)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def qr_svg(texto):
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(texto, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()


def qr_terminal(texto):
    import qrcode
    q = qrcode.QRCode(border=1)
    q.add_data(texto)
    q.make(fit=True)
    buf = io.StringIO()
    q.print_ascii(out=buf, invert=True)
    return buf.getvalue()


def limpiar(o):
    """Convierte tipos de numpy a Python y NaN/infinito a None (JSON válido para el navegador)."""
    import math

    import numpy as np
    if isinstance(o, dict):
        return {str(k): limpiar(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [limpiar(v) for v in o]
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return float(o) if math.isfinite(o) else None
    return o


def crear_app(motor, token=None, url_red=None):
    """Crea la aplicación FastAPI conectada al ``motor``."""
    token = token or secrets.token_urlsafe(6)
    app = FastAPI(title="AURA Vision", docs_url=None, redoc_url=None)
    app.state.token = token
    app.state.url_red = url_red
    app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")

    def verificar(t):
        if not secrets.compare_digest(str(t or ""), token):
            raise HTTPException(status_code=403, detail="Token inválido: abre el enlace que muestra la terminal.")

    @app.get("/", response_class=HTMLResponse)
    def inicio(t: str = ""):
        if not secrets.compare_digest(t, token):
            return HTMLResponse("<h2 style='font-family:sans-serif'>AURA Vision: abre el enlace completo (con ?t=...) "
                                "que muestra la terminal o el código QR.</h2>", status_code=403)
        with open(os.path.join(ESTATICOS, "index.html"), encoding="utf-8") as f:
            return f.read()

    @app.get("/api/estado")
    def estado(t: str = ""):
        verificar(t)
        datos, _ = motor.instantanea()
        return JSONResponse(limpiar(datos))

    @app.post("/api/comando")
    async def comando(request: Request, t: str = ""):
        verificar(t)
        c = await request.json()
        return JSONResponse(limpiar(await asyncio.to_thread(motor.comando, c)))

    @app.post("/api/marioneta")
    async def marioneta(request: Request, t: str = ""):
        verificar(t)
        try:
            return JSONResponse(motor.recibir_marioneta(await request.json()))
        except Exception as e:
            return JSONResponse({"ok": False, "mensaje": str(e)}, status_code=400)

    @app.post("/api/medido")
    async def medido(request: Request, t: str = ""):
        verificar(t)
        datos = await request.body()
        nombre = request.headers.get("x-nombre", "maqueta.csv")
        try:
            return JSONResponse(limpiar(motor.cargar_medido(datos, nombre)))
        except Exception as e:
            return JSONResponse({"ok": False, "mensaje": f"No se pudo leer el CSV: {e}"}, status_code=400)

    @app.get("/api/qr.svg")
    def qr(t: str = ""):
        verificar(t)
        return Response(qr_svg(app.state.url_red or "http://127.0.0.1"), media_type="image/svg+xml")

    @app.get("/api/info")
    def info(t: str = ""):
        verificar(t)
        return {"url_red": app.state.url_red}

    @app.get("/api/reporte")
    def reporte(t: str = ""):
        verificar(t)
        ruta = motor.ultimo_reporte
        if not ruta or not os.path.exists(ruta):
            raise HTTPException(404, "Aún no hay reporte: graba una sesión y detén la grabación.")
        return FileResponse(ruta, media_type="text/html")

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        if not secrets.compare_digest(websocket.query_params.get("t", ""), token):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        periodo = 1.0 / float(motor.cfg["interfaz"]["fps_envio"])
        try:
            while True:
                datos, jpeg = motor.instantanea()
                await websocket.send_text(json.dumps(limpiar(datos), allow_nan=False))
                if jpeg is not None:
                    await websocket.send_bytes(jpeg)
                await asyncio.sleep(periodo)
        except (WebSocketDisconnect, RuntimeError):
            pass

    return app
