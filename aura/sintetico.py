"""Persona sintética ("figura de palitos") con movimientos físicos conocidos.

Sirve para:
* los **tests** (caída libre, caminata, salto...) sin necesitar video;
* un **modo demo sin cámara ni modelos** (``python app.py --sintetico``), por si
  todo falla el día de la presentación.

Las proporciones son humanas (tablas de Winter) y los movimientos siguen la
física: la cadera cae libremente (h = h0 − g·t²/2), el salto es balístico.
"""

import numpy as np

from .vision.esqueleto import (FRAC_ALTURA_TOBILLO, FRAC_CADERA_HOMBRO, FRAC_RODILLA_CADERA, FRAC_TOBILLO_RODILLA,
                               KP, N_KP)

G = 9.81


def _pose(S, hx, hh, torso, m, p, brazos=(0.0, 0.0), dy=0.0):
    """17 puntos (x, altura) en metros para unos ángulos (grados) dados."""
    L_th, L_sh, L_t = FRAC_RODILLA_CADERA * S, FRAC_TOBILLO_RODILLA * S, FRAC_CADERA_HOMBRO * S
    k = np.zeros((N_KP, 2))
    hip = np.array([hx, hh + dy])
    f = np.radians(torso)
    u = np.array([np.sin(f), np.cos(f)])
    adelante = np.array([np.cos(f), -np.sin(f)])
    sh = hip + L_t * u
    cabeza = sh + 0.10 * S * u
    off = 0.006 * S
    for j, lado, s in ((0, "izq", -1), (1, "der", 1)):
        a_m, a_p = np.radians(m[j]), np.radians(p[j])
        cad = hip + np.array([s * off, 0])
        rod = cad + L_th * np.array([np.sin(a_m), -np.cos(a_m)])
        tob = rod + L_sh * np.array([np.sin(a_p), -np.cos(a_p)])
        hom = sh + np.array([s * off, 0])
        b = np.radians(brazos[j])
        codo = hom + 0.186 * S * np.array([np.sin(b), -np.cos(b)])
        mun = codo + 0.146 * S * np.array([np.sin(b + 0.2), -np.cos(b + 0.2)])
        k[KP[f"cadera_{lado}"]], k[KP[f"rodilla_{lado}"]], k[KP[f"tobillo_{lado}"]] = cad, rod, tob
        k[KP[f"hombro_{lado}"]], k[KP[f"codo_{lado}"]], k[KP[f"muneca_{lado}"]] = hom, codo, mun
        k[KP[f"ojo_{lado}"]] = cabeza + 0.03 * S * adelante + 0.012 * S * u
        k[KP[f"oreja_{lado}"]] = cabeza - 0.01 * S * adelante + np.array([s * off, 0])
    k[KP["nariz"]] = cabeza + 0.045 * S * adelante
    return k


def _h_piernas(S, m, p):
    proy = [FRAC_RODILLA_CADERA * S * np.cos(np.radians(m[j])) + FRAC_TOBILLO_RODILLA * S * np.cos(np.radians(p[j]))
            for j in (0, 1)]
    return FRAC_ALTURA_TOBILLO * S + max(proy)


def _suave(x):
    return 0.5 - 0.5 * np.cos(np.pi * np.clip(x, 0, 1))


class Escena:
    """Encadena fases de movimiento y genera una secuencia de poses a ``fps`` cuadros/s."""

    def __init__(self, S=1.70, fps=30.0, x0=1.0):
        self.S, self.fps, self.hx = S, fps, x0
        self.cuadros = []
        self.fases = []

    @property
    def t(self):
        return len(self.cuadros) / self.fps

    def _n(self, d):
        return int(round(d * self.fps))

    def _add(self, nombre, lista):
        t0 = self.t
        self.cuadros += lista
        self.fases.append((t0, self.t, nombre))
        return self

    def de_pie(self, dur):
        S = self.S
        return self._add("de_pie", [dict(hx=self.hx, hh=_h_piernas(S, (0, 0), (0, 0)),
                                         torso=2 + 0.4 * np.sin(2 * np.pi * 0.3 * i / self.fps),
                                         m=(0, 0), p=(0, 0), brazos=(3, -3)) for i in range(self._n(dur))])

    def caminar(self, dur, v=1.1, f=0.9):
        S, out = self.S, []
        for i in range(self._n(dur)):
            t = i / self.fps
            env = min(1.0, t / 0.3, (dur - t) / 0.3)
            fase = 2 * np.pi * f * t
            mL = 25 * np.sin(fase) * env
            m = (mL, -mL)
            p = (mL - 35 * max(0, -np.cos(fase)) * env, -mL - 35 * max(0, np.cos(fase)) * env)
            self.hx += v * env / self.fps
            out.append(dict(hx=self.hx, hh=_h_piernas(S, m, p), torso=5, m=m, p=p,
                            brazos=(-20 * np.sin(fase) * env, 20 * np.sin(fase) * env)))
        return self._add("caminando", out)

    def saltar(self, t_vuelo=0.45):
        S, out = self.S, []

        def piernas(a):
            return (40 * a, 40 * a), (-30 * a, -30 * a), 2 + 23 * a
        for i in range(self._n(0.35)):
            m, p, tor = piernas(_suave(i / self._n(0.35)))
            out.append(dict(hx=self.hx, hh=_h_piernas(S, m, p), torso=tor, m=m, p=p))
        for i in range(self._n(0.15)):
            m, p, tor = piernas(1 - _suave((i + 1) / self._n(0.15)))
            out.append(dict(hx=self.hx, hh=_h_piernas(S, m, p), torso=tor, m=m, p=p, brazos=(120, 120)))
        v0, hh0 = G * t_vuelo / 2, _h_piernas(S, (0, 0), (0, 0))
        for i in range(1, int(np.floor(t_vuelo * self.fps)) + 1):
            t = i / self.fps
            out.append(dict(hx=self.hx, hh=hh0, torso=2, m=(5, 5), p=(0, 0), brazos=(150, 150),
                            dy=max(0.0, v0 * t - 0.5 * G * t * t)))
        for i in range(self._n(0.3)):
            m, p, tor = piernas(np.sin(np.pi * (i + 1) / self._n(0.3)) * 0.6)
            out.append(dict(hx=self.hx, hh=_h_piernas(S, m, p), torso=tor, m=m, p=p))
        return self._add("saltando", out)

    def sentarse(self, dur=1.2, inverso=False):
        S, out, n = self.S, [], self._n(dur)
        for i in range(n):
            a = _suave((i + 1) / n)
            a = 1 - a if inverso else a
            out.append(dict(hx=self.hx, hh=_h_piernas(S, (90 * a, 90 * a), (0, 0)),
                            torso=2 + 28 * np.sin(np.pi * a) + 3 * a, m=(90 * a, 90 * a), p=(0, 0)))
        return self._add("levantarse" if inverso else "sentarse", out)

    def sentado(self, dur):
        S = self.S
        return self._add("sentado", [dict(hx=self.hx, hh=_h_piernas(S, (90, 90), (0, 0)), torso=5,
                                          m=(90, 90), p=(0, 0)) for _ in range(self._n(dur))])

    def _tumbado(self, a, hh):
        S = self.S
        cos_t = np.clip((hh - FRAC_ALTURA_TOBILLO * S) / ((FRAC_RODILLA_CADERA + FRAC_TOBILLO_RODILLA) * S), 0, 1)
        th = np.degrees(np.arccos(cos_t))
        return dict(hx=self.hx, hh=hh, torso=-88 * a, m=(th, th), p=(th, th), brazos=(110 * a, 90 * a))

    def caer(self):
        """Caída libre de la cadera hasta el suelo (el cuerpo gira hacia atrás)."""
        S = self.S
        h0, h1 = _h_piernas(S, (0, 0), (0, 0)), 0.06 * S
        T = np.sqrt(2 * (h0 - h1) / G)
        out = []
        for i in range(1, int(np.ceil(T * self.fps)) + 1):
            t = min(i / self.fps, T)
            hh = h0 - 0.5 * G * t * t
            out.append(self._tumbado((h0 - hh) / (h0 - h1), hh))
        return self._add("caida", out)

    def acostarse(self, dur=3.0):
        S = self.S
        h0, h1, n = _h_piernas(S, (0, 0), (0, 0)), 0.06 * S, self._n(dur)
        return self._add("acostarse", [self._tumbado(_suave((i + 1) / n), h0 - (h0 - h1) * _suave((i + 1) / n))
                                       for i in range(n)])

    def tumbado(self, dur):
        out = []
        for i in range(self._n(dur)):
            d = self._tumbado(1.0, 0.06 * self.S + 0.002 * self.S * np.sin(2 * np.pi * 0.25 * i / self.fps))
            d["m"], d["p"] = (88, 88), (85, 85)
            out.append(d)
        return self._add("en_el_suelo", out)


def a_pixeles(escena, ppm=250.0, suelo_px=650.0, ruido_px=1.0, conf=0.9, semilla=0):
    """Convierte la escena a cuadros de "detector": tiempos, puntos (N,17,2), confianzas y cajas."""
    rng = np.random.default_rng(semilla)
    S = escena.S
    T, K, C, B = [], [], [], []
    for i, prm in enumerate(escena.cuadros):
        k = _pose(S, **prm)
        px = np.stack([k[:, 0] * ppm, suelo_px - k[:, 1] * ppm], axis=1) + rng.normal(0, ruido_px, (N_KP, 2))
        f = np.radians(prm["torso"])
        cabeza = k[KP["nariz"]] + 0.07 * S * np.array([np.sin(f), np.cos(f)])
        top = suelo_px - max(cabeza[1], k[:, 1].max()) * ppm
        caja = np.array([px[:, 0].min() - 0.06 * S * ppm, min(top, px[:, 1].min()),
                         px[:, 0].max() + 0.06 * S * ppm, px[:, 1].max() + 0.03 * S * ppm])
        T.append(i / escena.fps)
        K.append(px)
        C.append(np.clip(rng.normal(conf, 0.03, N_KP), 0, 1))
        B.append(caja)
    return np.array(T), np.array(K), np.array(C), np.array(B)


def rutina_demo():
    """Rutina larga para el modo ``--sintetico``: de pie, camina, salta, se sienta, cae y queda en el suelo."""
    return (Escena(x0=1.0).de_pie(2).caminar(3).de_pie(1.5).saltar().de_pie(1.5).sentarse().sentado(3)
            .sentarse(inverso=True).de_pie(1.5).caminar(2, v=-1.1).de_pie(1).caer().tumbado(35).sentarse(1.5, inverso=True)
            .de_pie(2))


def dibujar_figura(kps, ancho=1280, alto=720, suelo_px=650):
    """Imagen BGR de la figura (para el modo sintético; el reconocimiento usa los puntos directamente)."""
    import cv2
    from .vision.esqueleto import ESQUELETO
    img = np.full((alto, ancho, 3), 200, np.uint8)
    cv2.rectangle(img, (0, int(suelo_px)), (ancho, alto), (150, 160, 170), -1)
    for a, b in ESQUELETO:
        cv2.line(img, tuple(int(v) for v in kps[a]), tuple(int(v) for v in kps[b]), (70, 70, 90), 12, cv2.LINE_AA)
    cv2.circle(img, tuple(int(v) for v in kps[0]), 24, (120, 150, 200), -1, cv2.LINE_AA)
    return img
