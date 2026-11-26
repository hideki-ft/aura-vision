"""Módulo de Colab: la capa que se dibuja sobre el video (sin modelos ni navegador)."""
from collections import deque

import numpy as np

from aura.colab import SesionColab


def test_capa_transparente_con_panel():
    s = SesionColab.__new__(SesionColab)           # sin cargar modelos
    s.V = deque([5, 6, 20, 25, 7], maxlen=300)
    k = np.array([[300 + 3 * j, 100 + 20 * j] for j in range(17)], float).tolist()
    d = {"estado": "incierto", "confianza": 0.3, "fps": 8.0, "motivo_incierto": "no se ven las piernas: aléjate",
         "personas": [{"id": 1, "caja": [280, 80, 360, 460], "kps": k, "scores": [0.9] * 17, "objetivo": True}],
         "fisica": {"h_m": 0.9, "vy": 0.0, "vx": 0.1}, "wifi": {"V": 7.0, "movimiento": False, "umbral_V": 10,
                                                           "f_esperada_hz": 1.0, "pico_hz": 2.0},
         "alerta_activa": "POSIBLE CAÍDA"}
    capa = s.dibujar_capa((480, 640, 3), d)
    assert capa.shape == (480, 640, 4)
    assert 0.02 < (capa[:, :, 3] > 0).mean() < 0.6       # casi todo transparente, con dibujos
    assert capa[470, 320, 3] == 255                        # franja de alerta abajo
