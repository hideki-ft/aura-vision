"""Simulador en tiempo real del sensor Wi-Fi virtual (CALCULADO).

La cámara entrega la posición de la persona ~15-30 veces por segundo; un sensor
Wi-Fi real mide ~100 veces por segundo. Entre dos cuadros se **interpola** la
posición y se calcula H(t) a 100 muestras/s para las 26 subportadoras, con
ruido gaussiano. Con eso se obtienen V, el espectro y las magnitudes físicas.
"""

from collections import deque

import numpy as np

from .canal import CanalWifi
from .metricas import (calcular_V, energia_banda, espectro, frecuencia_esperada, giro_de_fase, pico,
                       sigma_por_subportadora)


class SimuladorWifi:
    """Genera |H_k(t)| a ``muestras_por_s`` y calcula las métricas de la maqueta."""

    def __init__(self, cfg_wifi, semilla=None):
        self.cfg = cfg_wifi
        self.canal = CanalWifi(cfg_wifi)
        self.fs = float(cfg_wifi["muestras_por_s"])
        self.ruido = float(cfg_wifi["ruido_sigma"])
        esc = cfg_wifi.get("escala_V", "auto")
        self.escala_V = 5.0 / max(self.ruido, 1e-9) if esc in (None, "auto") else float(esc)
        self.umbral_V = float(cfg_wifi["umbral_V"])
        self.ventana_sigma = float(cfg_wifi["ventana_sigma_s"])
        self.ventana_welch = float(cfg_wifi["ventana_welch_s"])
        self.banda_energia = tuple(cfg_wifi["banda_energia_hz"])
        self.historial_s = float(cfg_wifi["historial_s"])
        self.rng = np.random.default_rng(semilla)
        n_max = int(self.fs * max(self.historial_s, self.ventana_welch + 2))
        self.t_buf = deque(maxlen=n_max)
        self.A_buf = deque(maxlen=n_max)
        self.pos = deque()                 # (t, x, y, presente) de la cámara, últimos 3 s
        self.V_hist = deque()              # (t, V)
        self.t_gen = None
        self.ultimo = None                 # (t, p, presente, z)

    # ------------------------------------------------------------------ controles
    def fijar_banda(self, banda_ghz):
        self.canal.fijar_banda(banda_ghz)

    def fijar_contraste(self, c):
        self.canal.contraste = float(np.clip(c, 0.0, 1.0))

    def calibrar_escala(self, V_objetivo=5.0, segundos=3.0):
        """Ajusta la escala para que el V actual (persona quieta) valga ``V_objetivo``."""
        t = np.array(self.t_buf)
        if len(t) < 10:
            return self.escala_V
        A = np.array(self.A_buf)[t >= t[-1] - segundos]
        crudo = calcular_V(A, 1.0)
        if crudo > 0:
            self.escala_V = V_objetivo / crudo
        return self.escala_V

    # ------------------------------------------------------------------ generación
    def alimentar(self, t, p=None, z=None):
        """Nueva posición de la cámara en el instante ``t`` (s). ``p`` = (x, y) en m o None si no hay persona.
        ``z`` = altura del tronco (m), solo para el modelo 3D opcional."""
        presente = p is not None and np.all(np.isfinite(p))
        p = np.asarray(p, float) if presente else np.array([np.nan, np.nan])
        z = float(z) if z is not None and np.isfinite(z) else np.nan
        self.pos.append((t, p[0], p[1], presente))
        while self.pos and self.pos[0][0] < t - 3:
            self.pos.popleft()
        if self.ultimo is None:
            self.ultimo = (t, p, presente, z)
            self.t_gen = t
            return
        t0, p0, pres0, z0 = self.ultimo
        n = int(np.floor((t - self.t_gen) * self.fs + 1e-9))
        if n > 0:
            ts = self.t_gen + np.arange(1, n + 1) / self.fs
            u = np.clip((ts - t0) / max(t - t0, 1e-9), 0, 1)[:, None]
            if presente and pres0:
                P = p0[None, :] + u * (p - p0)[None, :]
                pres = np.ones(n, bool)
            else:
                P = np.where(u < 0.5, p0, p) if (presente or pres0) else np.zeros((n, 2))
                pres = np.where(u[:, 0] < 0.5, pres0, presente)
            zz = None
            if self.canal.altura_antenas is not None and np.isfinite(z):
                zz = (z0 if np.isfinite(z0) else z) + u[:, 0] * (z - (z0 if np.isfinite(z0) else z))
            H = self.canal.H(np.nan_to_num(P), pres, zz)
            H = H + self.ruido * (self.rng.standard_normal(H.shape) + 1j * self.rng.standard_normal(H.shape))
            A = np.abs(H)
            self.t_buf.extend(ts.tolist())
            self.A_buf.extend(A)
            self.t_gen = ts[-1]
        self.ultimo = (t, p, presente, z)

    # ------------------------------------------------------------------ métricas
    def _ventana(self, segundos):
        if not self.t_buf:
            return np.zeros(0), np.zeros((0, self.canal.n_sub))
        t = np.fromiter(self.t_buf, float)
        k = np.searchsorted(t, t[-1] - segundos)
        A = np.array(list(self.A_buf)[k:])
        return t[k:], A

    def _velocidad(self):
        pts = [(t, x, y) for t, x, y, pr in self.pos if pr]
        if len(pts) < 3:
            return np.nan, np.nan, np.nan
        tt = np.array([q[0] for q in pts])
        m = tt >= tt[-1] - 0.5
        if m.sum() < 2 or np.ptp(tt[m]) < 0.05:
            return np.nan, np.nan, np.nan
        vx = np.polyfit(tt[m], [q[1] for q, mm in zip(pts, m) if mm], 1)[0]
        vy = np.polyfit(tt[m], [q[2] for q, mm in zip(pts, m) if mm], 1)[0]
        P = np.array([[q[1], q[2]] for q, mm in zip(pts, m) if mm])
        db = np.polyfit(tt[m], self.canal.d_cuerpo(P), 1)[0]
        return float(np.hypot(vx, vy)), float(db), float(tt[-1])

    def _desplazamiento_1s(self):
        pts = [(t, x, y) for t, x, y, pr in self.pos if pr]
        if len(pts) < 2:
            return np.nan
        t_fin = pts[-1][0]
        ini = min(pts, key=lambda q: abs(q[0] - (t_fin - 1.0)))
        if t_fin - ini[0] < 0.5:
            return np.nan
        return float(np.hypot(pts[-1][1] - ini[1], pts[-1][2] - ini[2]))

    def metricas(self, n_puntos_espectro=64):
        """Diccionario con V, espectro, energía, física y caminos (todo CALCULADO)."""
        lam = self.canal.lam
        t, A = self._ventana(self.ventana_sigma)
        V = calcular_V(A, self.escala_V) if len(A) >= 10 else 0.0
        t_now = float(t[-1]) if len(t) else 0.0
        self.V_hist.append((t_now, V))
        while self.V_hist and self.V_hist[0][0] < t_now - self.historial_s:
            self.V_hist.popleft()
        tw, Aw = self._ventana(self.ventana_welch)
        f, P = espectro(Aw, self.fs, nperseg=min(128, len(Aw))) if len(Aw) >= 32 else (np.array([]), np.array([]))
        v, d_db, _ = self._velocidad()
        dx = self._desplazamiento_1s()
        ult = self.ultimo
        p = ult[1] if ult and ult[2] else None
        z = ult[3] if ult and ult[2] and self.canal.altura_antenas is not None else None
        sig = sigma_por_subportadora(A) * self.escala_V if len(A) >= 2 else np.zeros(self.canal.n_sub)
        m = f <= 50
        return {
            "etiqueta": "CALCULADO",
            "t": t_now,
            "V": round(V, 2),
            "umbral_V": self.umbral_V,
            "movimiento": bool(V > self.umbral_V),
            "sigma_k": [round(float(s), 3) for s in sig],
            "amplitud_k": [round(float(a), 4) for a in (A[-1] if len(A) else np.zeros(self.canal.n_sub))],
            "espectro_f": [round(float(x), 2) for x in f[m]],
            "espectro_P": [float(x) for x in P[m]],
            "pico_hz": None if not np.isfinite(pico(f, P, self.banda_energia)) else round(pico(f, P, self.banda_energia), 2),
            "energia_banda": energia_banda(f, P, self.banda_energia),
            "banda_energia_hz": list(self.banda_energia),
            "banda_ghz": self.canal.banda,
            "f_central_ghz": round(self.canal.f_central / 1e9, 4),
            "lambda_m": round(lam, 4),
            "velocidad_ms": None if not np.isfinite(v) else round(v, 3),
            "f_esperada_hz": None if not np.isfinite(v) else round(frecuencia_esperada(v, lam), 2),
            "f_geometrica_hz": None if not np.isfinite(d_db) else round(abs(d_db) / lam, 2),
            "desplazamiento_1s_m": None if not np.isfinite(dx) else round(dx, 3),
            "delta_fase_rad": None if not np.isfinite(dx) else round(giro_de_fase(dx, lam), 2),
            "gamma_cuerpo": round(abs(self.canal.gamma_cuerpo), 3),
            "contraste": round(self.canal.contraste, 2),
            "posicion_m": None if p is None else [round(float(p[0]), 3), round(float(p[1]), 3)],
            "caminos": self.canal.caminos(p, z),
            "modelo": "3D" if self.canal.altura_antenas is not None else "2D (planta)",
            "escala_V": round(self.escala_V, 2),
        }

    def historial_V(self):
        return [[round(t, 2), round(v, 2)] for t, v in self.V_hist]
