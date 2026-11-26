"""Reglas de clasificación con secuencias sintéticas (caída, caminata, salto, ...), sin video."""
import numpy as np
import pytest

from aura.config import cargar_config
from aura.sintetico import Escena, a_pixeles
from aura.vision.clasificador import ClasificadorEstados, puntajes_posturas, rampa
from aura.vision.one_euro import OneEuroFilter

CFG = cargar_config()


def correr(escena, paso=1, ruido=1.0, semilla=0, quitar=None, filtrar=True):
    """Pasa la escena por el One Euro Filter y el clasificador como lo hace la app."""
    T, K, C, B = a_pixeles(escena, ruido_px=ruido, semilla=semilla)
    cl = ClasificadorEstados(CFG["clasificacion"], CFG["alertas"], escena.S)
    f = OneEuroFilter(**CFG["one_euro"])
    out = []
    for i in range(0, len(T), paso):
        if quitar and quitar[0] <= T[i] < quitar[1]:
            o = cl.actualizar(T[i])
        else:
            o = cl.actualizar(T[i], f(K[i], T[i]) if filtrar else K[i], C[i], B[i])
        out.append((T[i], dict(o)))
    return out


def frac(out, estado, a, b):
    sel = [o["estado"] for t, o in out if a <= t < b]
    return np.mean([e == estado for e in sel]) if sel else np.nan


def todas(out, clave):
    return [x for _, o in out for x in (o.get(clave) or [])]


@pytest.mark.parametrize("paso", [1, 2])
def test_caida_libre_termina_en_el_suelo(paso):
    out = correr(Escena().de_pie(3).caer().tumbado(35), paso=paso)
    assert frac(out, "de_pie", 1.0, 2.9) > 0.95
    caidas = [e for e in todas(out, "eventos") if e["tipo"] == "caida"]
    assert len(caidas) == 1
    assert 2.8 <= caidas[0]["t_inicio"] <= 3.3            # la caída real empieza en t = 3.0 s
    assert caidas[0]["duracion_descenso_s"] < 1.0
    assert frac(out, "caida", 4.5, 7.0) > 0.9               # se muestra "caida" unos segundos
    assert frac(out, "en_el_suelo", 8.0, 38.0) > 0.95
    msgs = [a["mensaje"] for a in todas(out, "alertas")]
    assert msgs == ["POSIBLE CAÍDA", "sigue en el suelo tras 30 s"]


def test_caminata():
    out = correr(Escena(x0=0.4).de_pie(1).caminar(4).de_pie(1.5))
    assert frac(out, "caminando", 2.0, 4.6) > 0.9
    assert frac(out, "de_pie", 5.8, 6.5) > 0.9
    assert not [e for e in todas(out, "eventos") if e["tipo"] == "caida"]
    vx = [o["vx"] for t, o in out if 2.5 < t < 4.0]
    assert np.median(vx) == pytest.approx(1.1, abs=0.15)    # velocidad horizontal en m/s


def test_salto_y_altura_por_tiempo_de_vuelo():
    out = correr(Escena().de_pie(2).saltar(t_vuelo=0.45).de_pie(2))
    assert frac(out, "saltando", 2.55, 2.85) > 0.9
    assert not [e for e in todas(out, "eventos") if e["tipo"] == "caida"]
    salto = out[-1][1]["ultimo_salto"]
    assert salto["t_vuelo_s"] == pytest.approx(0.45, abs=0.05)
    assert salto["altura_m"] == pytest.approx(9.81 * 0.45 ** 2 / 8, abs=0.06)


def test_sentarse_y_levantarse():
    out = correr(Escena().de_pie(2).sentarse().sentado(5).sentarse(inverso=True).de_pie(2))
    assert frac(out, "sentado", 4.0, 8.0) > 0.95
    assert frac(out, "de_pie", 10.0, 11.2) > 0.9
    assert not todas(out, "alertas")


def test_tumbarse_despacio_no_es_caida():
    out = correr(Escena().de_pie(2).acostarse(3.0).tumbado(6))
    assert frac(out, "en_el_suelo", 6.5, 11.0) > 0.95
    assert not [e for e in todas(out, "eventos") if e["tipo"] == "caida"]
    assert not todas(out, "alertas")


def test_ausente_cuando_no_hay_persona():
    out = correr(Escena().de_pie(6), quitar=(2.0, 4.0))
    assert frac(out, "ausente", 2.9, 4.0) > 0.95          # 0.5 s sin verla + 0.3 s de duración mínima
    assert frac(out, "de_pie", 4.8, 6.0) > 0.9


def test_incierto_sin_piernas_visibles():
    T, K, C, B = a_pixeles(Escena().de_pie(3))
    C[:, 11:] = 0.0  # ni caderas ni piernas
    cl = ClasificadorEstados(CFG["clasificacion"], CFG["alertas"], 1.70)
    estados = [cl.actualizar(T[i], K[i], C[i], B[i])["estado"] for i in range(len(T))]
    assert estados[-1] == "incierto"


def test_cinematica_en_unidades_si():
    out = correr(Escena().de_pie(3).caer().tumbado(3))
    h = np.median([o["h_m"] for t, o in out if 1 < t < 2.8])
    assert h == pytest.approx(0.53 * 1.70, abs=0.05)         # cadera de pie ≈ 0.90 m
    ay = [o["ay"] for t, o in out if 3.25 < t < 3.38 and np.isfinite(o.get("ay", np.nan))]
    assert np.median(ay) == pytest.approx(-9.81, abs=3.0)      # caída libre: a ≈ −g


def test_rampa_y_puntajes():
    assert rampa(0.5, 0, 1) == 0.5 and rampa(2, 1, 0) == 0.0 and rampa(np.nan, 0, 1) == 0.0
    P = puntajes_posturas(0.53, 3, 175, 3.0, 0.0, CFG["clasificacion"])
    assert max(P, key=P.get) == "de_pie"
    P = puntajes_posturas(0.06, 88, 170, 0.3, 0.0, CFG["clasificacion"])
    assert max(P, key=P.get) == "en_el_suelo"


def test_incierto_explica_el_motivo():
    """Si no se ven las piernas (persona sentada frente a la laptop), el estado es incierto y dice por qué."""
    T, K, C, B = a_pixeles(Escena().de_pie(2))
    C[:, 13:] = 0.0  # sin rodillas ni tobillos
    cl = ClasificadorEstados(CFG["clasificacion"], CFG["alertas"], 1.70)
    o = None
    for i in range(len(T)):
        o = cl.actualizar(T[i], K[i], C[i], B[i])
    assert o["estado"] == "incierto" and "piernas" in o["motivo_incierto"]
