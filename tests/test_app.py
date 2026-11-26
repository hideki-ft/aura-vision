"""Servidor (FastAPI + WebSocket) con el motor en modo sintético, grabación/reporte y ST-GCN++ opcional."""
import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from aura.config import cargar_config
from aura.motor import Motor
from aura.sesion import COLUMNAS
from aura.ui.servidor import crear_app


@pytest.fixture(scope="module")
def cliente(tmp_path_factory):
    cfg = cargar_config(cambios={"carpeta_sesiones": str(tmp_path_factory.mktemp("sesiones"))})
    motor = Motor(cfg, {"tipo": "sintetico"})
    motor.iniciar()
    time.sleep(3)
    app = crear_app(motor, token="secreto", url_red="http://192.168.1.2:8000/?t=secreto")
    with TestClient(app) as c:
        yield c, motor
    motor.detener()


def test_token_obligatorio(cliente):
    c, _ = cliente
    assert c.get("/").status_code == 403
    assert c.get("/api/estado").status_code == 403
    assert c.get("/?t=secreto").status_code == 200


def test_estado_json_valido(cliente):
    c, _ = cliente
    d = c.get("/api/estado?t=secreto").json()
    assert d["estado"] in ("de_pie", "caminando", "saltando", "sentado", "incierto", "en_el_suelo", "caida", "ausente")
    assert d["wifi"]["etiqueta"] == "CALCULADO" and len(d["wifi"]["caminos"]) in (4, 5)
    assert d["fps"] > 5
    json.dumps(d, allow_nan=False)


def test_websocket_envia_estado_y_video(cliente):
    c, _ = cliente
    with c.websocket_connect("/ws?t=secreto") as ws:
        texto = ws.receive_text()
        jpeg = ws.receive_bytes()
    assert json.loads(texto)["wifi"] is not None
    assert jpeg[:2] == b"\xff\xd8"


def test_comandos(cliente):
    c, m = cliente
    post = lambda d: c.post("/api/comando?t=secreto", json=d).json()  # noqa: E731
    assert post({"accion": "estatura", "valor": 1.6})["ok"] and m.estatura == 1.6
    assert post({"accion": "banda", "valor": "5.18"})["ok"] and abs(m.wifi.canal.lam - 0.0579) < 1e-3
    assert post({"accion": "contraste", "valor": 0})["ok"] and m.wifi.canal.gamma_cuerpo == 0
    assert post({"accion": "privacidad", "valor": True})["ok"]
    time.sleep(0.3)
    assert m.instantanea()[1] is None                      # en privacidad no se envía imagen
    post({"accion": "privacidad", "valor": False})
    post({"accion": "contraste", "valor": 1})
    assert post({"accion": "calibrar"})["ok"]
    post({"accion": "objetivo", "x": 0.2, "y": 0.9})
    assert post({"accion": "objetivo", "x": 0.8, "y": 0.9})["mensaje"].endswith("Calibración lista.")
    assert not post({"accion": "inventada"})["ok"]


def test_csv_medido(cliente):
    c, m = cliente
    r = c.post("/api/medido?t=secreto", content=b"tiempo,V\n0,5\n1,7\n2,15\n3,5\n", headers={"x-nombre": "real.csv"})
    assert r.json()["ok"]
    d = c.get("/api/estado?t=secreto").json()
    assert d["medido"]["etiqueta"] == "MEDIDO (maqueta)" and d["medido"]["V"] is not None


def test_grabacion_y_reporte(cliente):
    c, m = cliente
    post = lambda d: c.post("/api/comando?t=secreto", json=d).json()  # noqa: E731
    assert post({"accion": "grabar", "valor": True})["ok"]
    time.sleep(3.5)
    r = post({"accion": "grabar", "valor": False})
    import csv
    import os
    carpeta = os.path.dirname(r["reporte"])
    filas = list(csv.DictReader(open(os.path.join(carpeta, "sesion.csv"), encoding="utf-8")))
    assert list(filas[0].keys()) == COLUMNAS and len(filas) >= 2
    html = c.get("/api/reporte?t=secreto").text
    assert "CALCULADO" in html and "Tiempo en cada estado" in html and "data:image/png;base64" in html


def test_gcn_opcional_con_sesion_falsa():
    from aura.vision.gcn import ClasificadorGCN

    class Entrada:
        name, shape = "x", [1, 2, 100, 17, 3]

    class SesionFalsa:
        def get_inputs(self):
            return [Entrada()]

        def run(self, _, feed):
            assert feed["x"].shape == (1, 2, 100, 17, 3)
            z = np.zeros(120)
            z[42] = 5.0                                     # "caerse" (A43)
            return [z[None]]
    g = ClasificadorGCN({"cuadros": 100, "cada_n_cuadros": 10, "clases_interes": {42: "caerse"}}, sesion=SesionFalsa())
    kps = np.random.default_rng(0).normal(300, 50, (17, 2))
    r = None
    for _ in range(100):
        r = g.agregar(kps, np.ones(17)) or r
    assert r["nombre_top"] == "caerse" and r["prob_top"] > 0.5


def test_motor_detecta_la_caida_de_la_rutina_sintetica():
    """Flujo completo del motor (tracker + One Euro + reglas + Wi-Fi) con la rutina del modo --sintetico."""
    from aura.sintetico import a_pixeles, rutina_demo
    cfg = cargar_config()
    m = Motor(cfg, {"tipo": "sintetico"})
    T, K, C, B = a_pixeles(rutina_demo(), ruido_px=0.8)
    img = np.zeros((720, 1280, 3), np.uint8)
    estados = []
    for i in range(len(T)):
        m._procesar(img, T[i], (K[i], C[i], B[i]))
        estados.append(m.estado["estado"])
    caidas = [e for e in m.eventos if e["tipo"] == "caida"]
    assert len(caidas) == 1
    assert [a["mensaje"] for a in m.alertas][:2] == ["POSIBLE CAÍDA", "sigue en el suelo tras 30 s"]
    for e in ("de_pie", "caminando", "saltando", "sentado", "caida", "en_el_suelo"):
        assert e in estados, e
