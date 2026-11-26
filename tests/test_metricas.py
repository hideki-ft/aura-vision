"""Cálculo de V, espectro, energía, f = 2v/λ y Δφ = 4πΔx/λ."""
import numpy as np
import pytest

from aura.config import cargar_config
from aura.wifi_virtual.medido import cargar_csv_medido
from aura.wifi_virtual.metricas import (calcular_V, energia_banda, espectro, frecuencia_esperada, giro_de_fase, pico,
                                        serie_V)
from aura.wifi_virtual.simulador import SimuladorWifi

CFG = cargar_config()["wifi"]


def test_V_de_amplitudes_conocidas():
    A = np.ones((100, 26))
    assert calcular_V(A) == 0.0
    t = np.arange(100) / 100
    A = 1 + 0.2 * np.sin(2 * np.pi * 5 * t)[:, None] * np.ones((1, 26))
    assert calcular_V(A, escala=10) == pytest.approx(10 * 0.2 / np.sqrt(2), rel=1e-3)


def test_V_quieto_cerca_de_5_y_caminando_supera_el_umbral():
    quieto, caminando = SimuladorWifi(CFG, semilla=1), SimuladorWifi(CFG, semilla=1)
    for i in range(150):
        t = i / 15
        quieto.alimentar(t, (1.0, 0.8))
        caminando.alimentar(t, (1.0, 0.4 + 0.5 * (t % 4)))
        mq, mc = quieto.metricas(), caminando.metricas()
    assert 4.0 <= mq["V"] <= 6.0 and not mq["movimiento"]
    assert mc["V"] > CFG["umbral_V"] and mc["movimiento"]


def test_espectro_pico_y_energia():
    fs = 100
    t = np.arange(400) / fs
    A = 1 + 0.1 * np.sin(2 * np.pi * 8 * t)[:, None] * np.ones((1, 26))
    f, P = espectro(A, fs)
    assert pico(f, P) == pytest.approx(8, abs=0.8)
    assert energia_banda(f, P, (0.5, 20)) == pytest.approx(0.1 ** 2 / 2, rel=0.2)   # potencia de la senoide


def test_formulas():
    lam = 0.125
    assert frecuencia_esperada(1.0, lam) == pytest.approx(16.0)
    assert giro_de_fase(lam / 2, lam) == pytest.approx(2 * np.pi)


@pytest.mark.parametrize("banda,v", [("2.4", 0.5), ("2.4", 0.3), ("5.18", 0.4)])
def test_f_2v_lambda_aparece_en_el_espectro(banda, v):
    """Router y receptor casi juntos (monoestático): la persona se aleja a v → pico en f = 2v/λ."""
    cfg = dict(CFG, router_m=[0.05, 1.5], receptor_m=[0.05, 1.45], ruido_sigma=0.001, ventana_welch_s=4.0)
    s = SimuladorWifi(cfg, semilla=0)
    s.fijar_banda(banda)
    for i in range(int(6 * 15)):
        t = i / 15
        s.alimentar(t, (1.0 + v * t, 1.5))
    m = s.metricas()
    esperado = frecuencia_esperada(v, s.canal.lam)
    assert m["f_esperada_hz"] == pytest.approx(esperado, rel=0.05)
    assert m["pico_hz"] == pytest.approx(esperado, abs=1.0)
    assert m["f_geometrica_hz"] == pytest.approx(esperado, rel=0.05)


def test_csv_medido_formatos(tmp_path):
    p = tmp_path / "v.csv"
    p.write_text("tiempo,V\n0,5\n0.5,6\n1.0,12\n1.5,4\n")
    m = cargar_csv_medido(str(p))
    assert m["V"] == [5, 6, 12, 4] and m["etiqueta"] == "MEDIDO (maqueta)"
    t = np.arange(300) / 100
    cols = {f"sc{k}": 1 + 0.05 * np.sin(2 * np.pi * 3 * t + k) for k in range(26)}
    import pandas as pd
    pd.DataFrame({"tiempo_ms": t * 1000, **cols}).rename(columns={"tiempo_ms": "timestamp"}).to_csv(tmp_path / "s.csv", index=False)
    m2 = cargar_csv_medido(str(tmp_path / "s.csv"), escala=100)
    assert m2["tipo"] == "26 subportadoras"
    assert np.median(m2["V"]) == pytest.approx(100 * 0.05 / np.sqrt(2), rel=0.1)
    tv, V = serie_V(t, np.ones((300, 2)))
    assert np.allclose(V, 0)
