"""Puntos clave del cuerpo (formato COCO de 17 puntos) y medidas geométricas."""

import warnings

import numpy as np

KP = {
    "nariz": 0, "ojo_izq": 1, "ojo_der": 2, "oreja_izq": 3, "oreja_der": 4,
    "hombro_izq": 5, "hombro_der": 6, "codo_izq": 7, "codo_der": 8, "muneca_izq": 9, "muneca_der": 10,
    "cadera_izq": 11, "cadera_der": 12, "rodilla_izq": 13, "rodilla_der": 14, "tobillo_izq": 15, "tobillo_der": 16,
}
N_KP = 17
ESQUELETO = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12),
             (11, 13), (13, 15), (12, 14), (14, 16), (0, 1), (0, 2), (1, 3), (2, 4)]

# Proporciones del cuerpo como fracción de la estatura (tablas antropométricas de Winter)
FRAC_TOBILLO_RODILLA = 0.246
FRAC_RODILLA_CADERA = 0.245
FRAC_CADERA_HOMBRO = 0.288
FRAC_ALTURA_TOBILLO = 0.039
FRAC_CADENA = FRAC_TOBILLO_RODILLA + FRAC_RODILLA_CADERA + FRAC_CADERA_HOMBRO   # 0.779


def media_puntos(xy, idx):
    """Promedio de varios puntos ignorando los que faltan (NaN)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return np.nanmean(xy[idx], axis=0)


def puntos_validos(kps, scores, umbral):
    """Copia de los puntos con NaN donde la confianza es menor que ``umbral``."""
    xy = np.asarray(kps, float).copy()
    xy[np.asarray(scores) < umbral] = np.nan
    return xy


def angulo_torso(cadera, hombros):
    """Ángulo del tronco (cadera→hombros) con la vertical: 0° erguido, 90° horizontal."""
    v = hombros - cadera
    return float(np.degrees(np.arctan2(abs(v[0]), -v[1])))


def angulo_en(a, b, c):
    """Ángulo (grados) en el vértice ``b`` entre los segmentos b-a y b-c."""
    v1, v2 = a - b, c - b
    n = np.linalg.norm(v1) * np.linalg.norm(v2)
    if not np.isfinite(n) or n < 1e-9:
        return np.nan
    return float(np.degrees(np.arccos(np.clip(np.dot(v1, v2) / n, -1, 1))))


def estatura_aparente(xy):
    """Estatura en píxeles a partir de tobillo→rodilla→cadera→hombro (casi no depende de la postura)."""
    piernas = []
    for lado in ("izq", "der"):
        a, k, h = xy[KP[f"tobillo_{lado}"]], xy[KP[f"rodilla_{lado}"]], xy[KP[f"cadera_{lado}"]]
        piernas.append(np.linalg.norm(a - k) + np.linalg.norm(k - h))
    piernas = [p for p in piernas if np.isfinite(p)]
    cad = media_puntos(xy, [11, 12])
    hom = media_puntos(xy, [5, 6])
    tronco = np.linalg.norm(hom - cad)
    if piernas and np.isfinite(tronco):
        return float((np.mean(piernas) + tronco) / FRAC_CADENA)
    return np.nan


def caja_de_puntos(kps, scores, umbral=0.3, margen=0.15):
    """Caja que encierra los puntos fiables, ampliada un ``margen`` (para seguir sin detector)."""
    m = np.asarray(scores) >= umbral
    if m.sum() < 4:
        return None
    p = np.asarray(kps)[m]
    x1, y1 = p.min(0)
    x2, y2 = p.max(0)
    w, h = x2 - x1, y2 - y1
    return np.array([x1 - margen * w, y1 - margen * h - 0.06 * h, x2 + margen * w, y2 + margen * h])
