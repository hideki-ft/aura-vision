"""Métricas del Wi-Fi (CALCULADAS), las mismas que en la maqueta con ESP32.

* |H_k|: amplitud de cada subportadora k.
* σ_k: desviación estándar de |H_k| en una ventana de 1 s (cuánto "tiembla" cada subportadora).
* V = escala · promedio_k(σ_k). Con la escala elegida, V ≈ 5 con la persona quieta.
* Movimiento si V > umbral (10).
* Espectro de Welch de |H_k| (media quitada) promediado sobre k, y su energía en 0.5–20 Hz.
* Física: f = 2v/λ (frecuencia esperada al moverse a velocidad v) y Δφ = 4π·Δx/λ (giro de fase).
"""

import numpy as np
from scipy.signal import welch

_integrar = getattr(np, "trapezoid", None) or np.trapz   # numpy 2 renombró trapz -> trapezoid


def sigma_por_subportadora(A):
    """σ_k de una ventana de amplitudes A (N muestras × K subportadoras)."""
    A = np.asarray(A, float)
    return A.std(axis=0) if len(A) >= 2 else np.zeros(A.shape[1] if A.ndim == 2 else 1)


def calcular_V(A, escala=1.0):
    """V = escala · media(σ_k)."""
    return float(np.mean(sigma_por_subportadora(A)) * escala)


def espectro(A, fs, nperseg=128):
    """Espectro de Welch (densidad de potencia) promediado sobre subportadoras. Devuelve (f, P)."""
    A = np.asarray(A, float)
    n = min(nperseg, len(A))
    if n < 8:
        return np.array([]), np.array([])
    f, P = welch(A, fs=fs, nperseg=n, noverlap=n // 2, detrend="constant", axis=0)
    return f, P.mean(axis=1)


def energia_banda(f, P, banda=(0.5, 20.0)):
    """Energía (integral de la densidad espectral) entre banda[0] y banda[1] Hz."""
    if len(f) == 0:
        return 0.0
    m = (f >= banda[0]) & (f <= banda[1])
    return float(_integrar(P[m], f[m])) if m.sum() >= 2 else 0.0


def pico(f, P, banda=(0.5, 20.0)):
    """Frecuencia del máximo del espectro dentro de la banda (Hz) o NaN."""
    if len(f) == 0:
        return np.nan
    m = (f >= banda[0]) & (f <= banda[1])
    return float(f[m][np.argmax(P[m])]) if m.any() else np.nan


def frecuencia_esperada(v, lam):
    """f = 2v/λ: el camino reflejado cambia 2·Δx cuando la persona avanza Δx (aprox. monoestática)."""
    return 2.0 * abs(v) / lam


def giro_de_fase(dx, lam):
    """Δφ = 4π·Δx/λ (radianes) para un desplazamiento Δx."""
    return 4.0 * np.pi * abs(dx) / lam


def serie_V(t, A, escala=1.0, ventana_s=1.0, paso_s=0.1):
    """V(t) deslizante de una grabación: ventanas de ``ventana_s`` cada ``paso_s``. Devuelve (t_centros, V)."""
    t = np.asarray(t, float)
    A = np.asarray(A, float)
    if A.ndim == 1:
        A = A[:, None]
    ts, vs = [], []
    t0 = t[0]
    while t0 + ventana_s <= t[-1] + 1e-9:
        m = (t >= t0) & (t < t0 + ventana_s)
        if m.sum() >= 2:
            ts.append(t0 + ventana_s)
            vs.append(calcular_V(A[m], escala))
        t0 += paso_s
    return np.array(ts), np.array(vs)
