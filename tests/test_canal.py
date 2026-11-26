"""Suma de caminos (método de imágenes): habitación vacía, |Γ| = 0, geometría y bloqueo."""
import numpy as np
import pytest

from aura.config import cargar_config
from aura.wifi_virtual.canal import C_LUZ, CanalWifi, frecuencias_subportadoras
from aura.wifi_virtual.simulador import SimuladorWifi

CFG = cargar_config()["wifi"]


def test_subportadoras():
    f = frecuencias_subportadoras(2.412e9, 26, 312.5e3)
    assert len(f) == 26 and np.allclose(np.diff(f), 312.5e3) and f.mean() == pytest.approx(2.412e9)


def test_lambda_de_las_dos_bandas():
    c = CanalWifi(CFG)
    assert c.lam == pytest.approx(0.1243, abs=1e-3)          # 2.412 GHz (≈ 0.125 m del informe)
    c.fijar_banda("5.18")
    assert c.lam == pytest.approx(0.0579, abs=1e-4)


def test_habitacion_vacia_H_constante():
    """Sin persona (y sin ruido) |H| no cambia con el tiempo: es la referencia."""
    cfg = dict(CFG, ruido_sigma=0.0)
    s = SimuladorWifi(cfg)
    for i in range(60):
        s.alimentar(i / 15, None)
    A = np.array(s.A_buf)
    assert len(A) > 300 and np.allclose(A, A[0])
    assert np.allclose(A[0], np.abs(s.canal.H_vacia()))


def test_gamma_cero_la_persona_no_cambia_H():
    """Con |Γ| = 0 la persona es invisible: H es igual que la habitación vacía en cualquier posición."""
    c = CanalWifi(CFG)
    c.contraste = 0.0
    P = np.array([[1.0, 0.5], [1.0, 1.5], [2.5, 2.0], [1.0, 1.45]])   # incluye cruzar el camino directo
    assert np.allclose(c.H(P), c.H_vacia()[None, :])


def test_con_gamma_la_persona_si_cambia_H():
    c = CanalWifi(CFG)
    assert not np.allclose(c.H([[1.0, 0.5]]), c.H([[1.0, 0.6]]))


def test_metodo_de_imagenes_y_signos():
    c = CanalWifi(CFG)
    assert c.pared_router == "izquierda"
    d = {x["nombre"]: x["d"] for x in c.caminos_pared}
    T, R = np.array(CFG["router_m"]), np.array(CFG["receptor_m"])
    assert d["pared derecha"] == pytest.approx(np.linalg.norm([2 * 4.0 - T[0] - R[0], 0]))
    assert d["pared inferior"] == pytest.approx(np.hypot(R[0] - T[0], T[1] + R[1]))
    assert all(x["a"] < 0 for x in c.caminos_pared)          # inversión de fase 180° en el concreto
    cam = c.caminos([1.0, 0.5])
    assert len(cam) == 5 and cam[-1]["nombre"] == "cuerpo"
    assert c.gamma_cuerpo == pytest.approx(-0.763)


def test_H_es_la_suma_de_caminos():
    c = CanalWifi(CFG)
    p = np.array([1.2, 0.7])
    f = c.freqs
    H = (1 / c.d_directo) * np.exp(-2j * np.pi * c.d_directo * f / C_LUZ)
    for w in c.caminos_pared:
        H += w["a"] * np.exp(-2j * np.pi * w["d"] * f / C_LUZ)
    db = np.linalg.norm(p - c.T) + np.linalg.norm(c.R - p)
    H += (-0.763 / db) * np.exp(-2j * np.pi * db * f / C_LUZ)
    assert np.allclose(c.H([p])[0], H)


def test_bloqueo_del_camino_directo():
    c = CanalWifi(CFG)
    assert c.factor_bloqueo([[1.0, 1.5]])[0] == pytest.approx(CFG["transmision_bloqueo"])
    assert c.factor_bloqueo([[1.0, 0.5]])[0] == pytest.approx(1.0)


def test_modelo_3d_opcional_ve_las_caidas():
    """En 2D (planta) bajar la altura no cambia H; en 3D (antenas a 1 m) sí cambia el camino del cuerpo."""
    p = [[1.0, 0.6]]
    c2 = CanalWifi(CFG)
    assert np.allclose(c2.H(p, z=[1.1]), c2.H(p, z=[0.2]))
    c3 = CanalWifi(dict(CFG, altura_antenas_m=1.0))
    assert not np.allclose(c3.H(p, z=[1.1]), c3.H(p, z=[0.2]))
    assert c3.d_cuerpo(p, [1.0])[0] == pytest.approx(c2.d_cuerpo(p)[0])   # a la altura de las antenas = 2D
