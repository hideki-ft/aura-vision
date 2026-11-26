"""Mapeo de la imagen a la habitación (vista de planta) con una calibración de 2 puntos.

Supuesto: cámara lateral y persona que se mueve sobre una recta del piso.
El usuario marca en el video dos puntos del piso (A y B) y en config.yaml se
indica a qué posición de la habitación (m) corresponde cada uno. La posición
de la persona es la proyección del punto del piso bajo su cadera sobre A-B:

    s = (P − A_px)·(B_px − A_px) / |B_px − A_px|²,    posición = A_m + s·(B_m − A_m)

Sin calibrar, se usa la escala de la estatura (m/px) y el centro de la imagen
corresponde al punto medio de A-B.
"""

import numpy as np


class Calibracion:
    def __init__(self, cfg_cal, cfg_wifi=None):
        self.A_m = np.array(cfg_cal["punto_A_m"], float)
        self.B_m = np.array(cfg_cal["punto_B_m"], float)
        self.A_px = None if cfg_cal.get("pixeles_A") is None else np.array(cfg_cal["pixeles_A"], float)
        self.B_px = None if cfg_cal.get("pixeles_B") is None else np.array(cfg_cal["pixeles_B"], float)
        hab = (cfg_wifi or {}).get("habitacion", {"ancho_m": 1e9, "largo_m": 1e9})
        self.limites = (float(hab["ancho_m"]), float(hab["largo_m"]))
        self.pendiente = None   # "A" o "B" mientras el usuario está marcando

    @property
    def calibrada(self):
        return self.A_px is not None and self.B_px is not None

    def fijar_punto(self, cual, x, y):
        """Guarda el punto A o B (píxeles de la imagen)."""
        if cual == "A":
            self.A_px = np.array([x, y], float)
        else:
            self.B_px = np.array([x, y], float)

    def posicion(self, x_px, y_suelo_px, m_por_px, ancho_img):
        """Posición (x, y) en metros en la habitación, o None si faltan datos."""
        L = float(np.linalg.norm(self.B_m - self.A_m))
        if self.calibrada:
            ab = self.B_px - self.A_px
            s = float(np.dot(np.array([x_px, y_suelo_px]) - self.A_px, ab) / max(ab @ ab, 1e-9))
        elif np.isfinite(m_por_px) and np.isfinite(x_px) and L > 0:
            s = 0.5 + (x_px - ancho_img / 2) * m_por_px / L
        else:
            return None
        if not np.isfinite(s):
            return None
        p = self.A_m + np.clip(s, -0.1, 1.1) * (self.B_m - self.A_m)
        return np.clip(p, [0.05, 0.05], [self.limites[0] - 0.05, self.limites[1] - 0.05])

    def a_dict(self):
        return {"calibrada": self.calibrada, "A_px": None if self.A_px is None else self.A_px.tolist(),
                "B_px": None if self.B_px is None else self.B_px.tolist(), "A_m": self.A_m.tolist(),
                "B_m": self.B_m.tolist(), "pendiente": self.pendiente}
