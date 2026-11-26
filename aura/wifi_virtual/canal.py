"""Canal Wi-Fi por suma de caminos (método de imágenes). TODO lo de aquí es CALCULADO.

Una onda que va del router (T) al receptor (R) llega por varios caminos. Cada
camino n tiene una longitud d_n y una amplitud a_n; en el receptor se suman:

    H(f) = Σ_n a_n · e^(−j·2π·d_n/λ),    λ = c / f

Caminos del modelo (5):

* **directo** T→R, amplitud 1/d. Si el cuerpo se interpone, se atenúa.
* **3 reflexiones en paredes** (método de imágenes): se refleja T en la pared
  como en un espejo (T'); el camino mide |T'−R|. Amplitud Γ_pared/d, con
  Γ_pared < 0 (inversión de fase de 180° al reflejarse en el concreto).
  La pared donde está el router no genera camino propio.
* **reflexión en el cuerpo** T→persona→R, amplitud Γ_cuerpo/d, Γ_cuerpo = −0.763.

Cuando la persona se mueve, solo cambia d del camino del cuerpo (y el bloqueo
del directo): su fase gira y el |H| sube y baja. Eso es lo que "ve" el Wi-Fi.
"""

import numpy as np

C_LUZ = 299_792_458.0


def frecuencias_subportadoras(f_central_hz, n=26, espaciado_hz=312.5e3):
    """n subportadoras centradas en ``f_central_hz`` separadas ``espaciado_hz``."""
    k = np.arange(n) - (n - 1) / 2
    return f_central_hz + k * espaciado_hz


def distancia_a_segmento(p, a, b):
    """Distancia del punto p (o puntos (M,2)) al segmento a-b."""
    p = np.atleast_2d(p).astype(float)
    a, b = np.asarray(a, float), np.asarray(b, float)
    ab = b - a
    u = np.clip(((p - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
    return np.linalg.norm(p - (a + u[:, None] * ab), axis=1)


class CanalWifi:
    """Geometría de la habitación y cálculo de H para una o muchas posiciones de la persona."""

    def __init__(self, cfg_wifi):
        w = cfg_wifi
        self.ancho = float(w["habitacion"]["ancho_m"])
        self.largo = float(w["habitacion"]["largo_m"])
        self.T = np.array(w["router_m"], float)
        self.R = np.array(w["receptor_m"], float)
        self.gamma_pared = float(w["gamma_pared"])
        self.gamma_cuerpo_nominal = float(w["gamma_cuerpo"])
        self.contraste = float(w.get("contraste_cuerpo", 1.0))
        self.radio = float(w["radio_cuerpo_m"])
        z = w.get("altura_antenas_m")
        self.altura_antenas = None if z in (None, "null") else float(z)
        self.transmision = float(w["transmision_bloqueo"])
        self.n_sub = int(w["subportadoras"])
        self.espaciado = float(w["espaciado_khz"]) * 1e3
        self.frecuencias_banda = {str(k): float(v) for k, v in w["frecuencias_ghz"].items()}
        self.fijar_banda(w["banda_ghz"])
        paredes = {"izquierda": ("x", 0.0), "derecha": ("x", self.ancho),
                   "inferior": ("y", 0.0), "superior": ("y", self.largo)}
        dist = {n: abs(self.T[0 if e == "x" else 1] - v) for n, (e, v) in paredes.items()}
        self.pared_router = min(dist, key=dist.get)
        self.paredes = {n: pv for n, pv in paredes.items() if n != self.pared_router}
        self._precalcular()

    # ------------------------------------------------------------------ configuración
    def fijar_banda(self, banda_ghz):
        clave = str(banda_ghz)
        f_ghz = self.frecuencias_banda.get(clave, float(banda_ghz))
        self.banda = clave
        self.f_central = f_ghz * 1e9
        self.freqs = frecuencias_subportadoras(self.f_central, self.n_sub, self.espaciado)
        self.lam = C_LUZ / self.f_central
        if hasattr(self, "paredes"):
            self._precalcular()

    @property
    def gamma_cuerpo(self):
        """Γ efectivo del cuerpo = Γ nominal × contraste (0 = invisible)."""
        return self.gamma_cuerpo_nominal * self.contraste

    def _imagen(self, punto, eje, valor):
        q = np.array(punto, float)
        i = 0 if eje == "x" else 1
        q[i] = 2 * valor - q[i]
        return q

    def _punto_reflexion(self, img, eje, valor):
        i = 0 if eje == "x" else 1
        u = (valor - img[i]) / (self.R[i] - img[i])
        return img + u * (self.R - img)

    def _precalcular(self):
        """Caminos que no dependen de la persona: directo (sin bloqueo) y paredes."""
        self.d_directo = float(np.linalg.norm(self.R - self.T))
        self.caminos_pared = []
        for nombre, (eje, valor) in self.paredes.items():
            img = self._imagen(self.T, eje, valor)
            d = float(np.linalg.norm(self.R - img))
            self.caminos_pared.append({"nombre": f"pared {nombre}", "d": d, "a": self.gamma_pared / d,
                                       "puntos": [self.T.tolist(), self._punto_reflexion(img, eje, valor).tolist(),
                                                  self.R.tolist()]})
        f = self.freqs
        self.H_paredes = sum(c["a"] * np.exp(-2j * np.pi * c["d"] * f / C_LUZ) for c in self.caminos_pared)
        self.fase_directo = np.exp(-2j * np.pi * self.d_directo * f / C_LUZ)

    # ------------------------------------------------------------------ física
    def factor_bloqueo(self, P):
        """Amplitud relativa del camino directo (1 = libre). Transición suave de 10 cm en el borde del cuerpo."""
        P = np.atleast_2d(P)
        d = distancia_a_segmento(P, self.T, self.R)
        w = np.clip((self.radio + 0.10 - d) / 0.10, 0, 1)
        contraste = min(abs(self.contraste), 1.0)
        return 1 - w * contraste * (1 - self.transmision)

    def d_cuerpo(self, P, z=None):
        """Longitud del camino router→cuerpo→receptor. Con ``z`` (altura del tronco, m) y antenas a
        ``altura_antenas_m``, se usa la distancia 3D (modelo 3D opcional)."""
        P = np.atleast_2d(P)
        d1 = np.linalg.norm(P - self.T, axis=1)
        d2 = np.linalg.norm(self.R - P, axis=1)
        if z is not None and self.altura_antenas is not None:
            dz = np.nan_to_num(np.asarray(z, float) - self.altura_antenas)
            d1, d2 = np.hypot(d1, dz), np.hypot(d2, dz)
        return d1 + d2

    def H(self, P, presente=None, z=None):
        """H (M, K) para M posiciones de la persona (M, 2). ``presente`` (M,) False = habitación vacía.
        ``z`` (M,) = altura del tronco, solo se usa en el modelo 3D."""
        P = np.atleast_2d(np.asarray(P, float))
        M = len(P)
        pres = np.ones(M, bool) if presente is None else np.asarray(presente, bool)
        f = self.freqs[None, :]
        a0 = np.where(pres, self.factor_bloqueo(np.nan_to_num(P)), 1.0) / self.d_directo
        Hd = a0[:, None] * self.fase_directo[None, :]
        db = self.d_cuerpo(np.nan_to_num(P), z)
        ab = np.where(pres, self.gamma_cuerpo / db, 0.0)
        Hb = ab[:, None] * np.exp(-2j * np.pi * db[:, None] * f / C_LUZ)
        return Hd + self.H_paredes[None, :] + Hb

    def H_vacia(self):
        """Canal de referencia sin persona (constante en el tiempo)."""
        return self.H(np.zeros((1, 2)), presente=[False])[0]

    def caminos(self, p=None, z=None):
        """Los 5 caminos para dibujarlos: nombre, puntos (polilínea), longitud y |amplitud|."""
        out = []
        bloqueo = float(self.factor_bloqueo(p)[0]) if p is not None else 1.0
        out.append({"nombre": "directo", "puntos": [self.T.tolist(), self.R.tolist()], "d": self.d_directo,
                    "amplitud": bloqueo / self.d_directo, "bloqueado": bloqueo < 0.999})
        for c in self.caminos_pared:
            out.append({"nombre": c["nombre"], "puntos": c["puntos"], "d": c["d"], "amplitud": abs(c["a"]),
                        "bloqueado": False})
        if p is not None:
            d = float(self.d_cuerpo(p, None if z is None else [z])[0])
            out.append({"nombre": "cuerpo", "puntos": [self.T.tolist(), list(map(float, p)), self.R.tolist()],
                        "d": d, "amplitud": abs(self.gamma_cuerpo) / d, "bloqueado": False})
        return out
