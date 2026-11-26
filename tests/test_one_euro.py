"""Pruebas del One Euro Filter."""
import numpy as np

from aura.vision.one_euro import OneEuroFilter


def test_senal_constante_no_cambia():
    f = OneEuroFilter(1.0, 0.0)
    for i in range(50):
        y = f(np.array([3.0, -2.0]), i / 30)
    assert np.allclose(y, [3.0, -2.0])


def test_reduce_el_temblor_en_reposo():
    rng = np.random.default_rng(0)
    f = OneEuroFilter(min_cutoff=1.0, beta=0.0)
    x = 100 + rng.normal(0, 2.0, 300)
    y = np.array([f(v, i / 30) for i, v in enumerate(x)]).ravel()
    assert y[30:].std() < 0.5 * x[30:].std()


def test_beta_reduce_el_retraso_en_movimiento_rapido():
    t = np.arange(0, 2, 1 / 30)
    x = 300 * t                     # 300 px/s
    lento, rapido = OneEuroFilter(1.0, 0.0), OneEuroFilter(1.0, 0.05)
    y0 = [float(lento(v, ti)) for v, ti in zip(x, t)]
    y1 = [float(rapido(v, ti)) for v, ti in zip(x, t)]
    assert abs(x[-1] - y1[-1]) < 0.5 * abs(x[-1] - y0[-1])


def test_nan_mantiene_el_ultimo_valor():
    f = OneEuroFilter(1.0, 0.0)
    f(np.array([1.0, 1.0]), 0.0)
    y = f(np.array([np.nan, 2.0]), 0.1)
    assert y[0] == 1.0 and 1.0 < y[1] <= 2.0
