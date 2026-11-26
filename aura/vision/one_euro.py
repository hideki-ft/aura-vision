"""One Euro Filter: suavizado adaptativo de señales ruidosas en tiempo real.

Idea (Casiez, Roussel y Vogel, 2012): un filtro pasa-bajos cuya frecuencia de
corte sube cuando la señal se mueve rápido.

* Persona quieta  -> corte bajo  -> se elimina el temblor de los puntos clave.
* Persona rápida  -> corte alto  -> casi no hay retraso.

Fórmulas, con Te = tiempo entre muestras:
    α(fc)  = 1 / (1 + τ/Te),  τ = 1 / (2π·fc)
    dx̂     = filtro(α(d_cutoff), (x − x̂_anterior)/Te)
    fc     = min_cutoff + β·|dx̂|
    x̂      = filtro(α(fc), x)
"""

import math

import numpy as np


def _alfa(te, cutoff):
    tau = 1.0 / (2 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / te)


class OneEuroFilter:
    """Filtro One Euro para un arreglo de cualquier forma (p. ej. 17 puntos × 2 coordenadas)."""

    def __init__(self, min_cutoff=1.0, beta=0.0, d_cutoff=1.0):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self.x_prev = None
        self.dx_prev = None
        self.t_prev = None

    def reiniciar(self):
        self.x_prev = self.dx_prev = self.t_prev = None

    def __call__(self, x, t):
        """Filtra la muestra ``x`` tomada en el instante ``t`` (segundos). Los NaN se dejan pasar."""
        x = np.asarray(x, dtype=float)
        if self.x_prev is None:
            self.x_prev, self.dx_prev, self.t_prev = x.copy(), np.zeros_like(x), float(t)
            return x.copy()
        te = float(t) - self.t_prev
        if te <= 0:
            return self.x_prev.copy()
        # Si un punto aparece de nuevo tras faltar (NaN), se reinicia ese punto.
        nuevo = np.isnan(self.x_prev) & ~np.isnan(x)
        xp = np.where(nuevo, x, self.x_prev)
        dx = (x - xp) / te
        a_d = _alfa(te, self.d_cutoff)
        dx_hat = a_d * dx + (1 - a_d) * np.where(nuevo, 0.0, self.dx_prev)
        cutoff = self.min_cutoff + self.beta * np.abs(dx_hat)
        tau = 1.0 / (2 * np.pi * cutoff)
        a = 1.0 / (1.0 + tau / te)
        x_hat = a * x + (1 - a) * xp
        x_hat = np.where(np.isnan(x), xp, x_hat)          # dato faltante: se mantiene el anterior
        self.x_prev = x_hat
        self.dx_prev = np.where(np.isnan(dx_hat), 0.0, dx_hat)
        self.t_prev = float(t)
        return x_hat.copy()
