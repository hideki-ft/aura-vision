"""Seguimiento de personas con un ID estable: ByteTrack ligero con filtro de Kalman.

Cómo funciona, en tres ideas:

1. **Predicción (filtro de Kalman):** cada persona seguida tiene una caja y una
   velocidad estimadas. En cada cuadro se predice dónde estará su caja
   (modelo de velocidad constante) y cuánta incertidumbre hay.
2. **Asociación:** se compara cada caja detectada con cada caja predicha usando
   el IoU (área de la intersección / área de la unión). El algoritmo húngaro
   empareja de forma óptima. ByteTrack lo hace en dos pasadas: primero con las
   detecciones seguras y luego con las débiles (personas parcialmente tapadas).
3. **Corrección:** la caja emparejada corrige la predicción del filtro.

Las detecciones sin pareja crean IDs nuevos; los IDs que dejan de verse más de
``max_perdido_s`` segundos se eliminan.
"""

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import linear_sum_assignment


class FiltroKalmanCaja:
    """Filtro de Kalman sobre (cx, cy, a, h) + velocidades; a = ancho/alto (como en ByteTrack)."""

    def __init__(self):
        n = 4
        self.F = np.eye(2 * n)
        for i in range(n):
            self.F[i, n + i] = 1.0
        self.Hm = np.eye(n, 2 * n)
        self.w_pos = 1.0 / 20
        self.w_vel = 1.0 / 160

    def iniciar(self, z):
        media = np.r_[z, np.zeros(4)]
        h = z[3]
        std = [2 * self.w_pos * h, 2 * self.w_pos * h, 1e-2, 2 * self.w_pos * h,
               10 * self.w_vel * h, 10 * self.w_vel * h, 1e-5, 10 * self.w_vel * h]
        return media, np.diag(np.square(std))

    def predecir(self, media, cov):
        h = media[3]
        std = [self.w_pos * h, self.w_pos * h, 1e-2, self.w_pos * h,
               self.w_vel * h, self.w_vel * h, 1e-5, self.w_vel * h]
        Q = np.diag(np.square(std))
        return self.F @ media, self.F @ cov @ self.F.T + Q

    def corregir(self, media, cov, z):
        h = media[3]
        R = np.diag(np.square([self.w_pos * h, self.w_pos * h, 1e-1, self.w_pos * h]))
        S = self.Hm @ cov @ self.Hm.T + R
        K = cho_solve(cho_factor(S, lower=True), (cov @ self.Hm.T).T).T
        media = media + K @ (z - self.Hm @ media)
        cov = cov - K @ S @ K.T
        return media, cov


def xyxy_a_xyah(b):
    w, h = b[2] - b[0], b[3] - b[1]
    return np.array([b[0] + w / 2, b[1] + h / 2, w / max(h, 1e-6), h])


def xyah_a_xyxy(m):
    cx, cy, a, h = m[:4]
    w = a * h
    return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])


def iou_matriz(a, b):
    """IoU entre cada caja de ``a`` (N,4) y cada caja de ``b`` (M,4), en formato x1,y1,x2,y2."""
    a = np.asarray(a, float).reshape(-1, 4)
    b = np.asarray(b, float).reshape(-1, 4)
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(area_a[:, None] + area_b[None, :] - inter, 1e-9)


class Pista:
    """Una persona seguida (track)."""

    def __init__(self, id_, caja, score, t, kf):
        self.id = id_
        self.kf = kf
        self.media, self.cov = kf.iniciar(xyxy_a_xyah(caja))
        self.score = float(score)
        self.aciertos = 1
        self.t_visto = float(t)
        self.t_creada = float(t)
        self.confirmada = False
        self.det_idx = None

    @property
    def caja(self):
        return xyah_a_xyxy(self.media)

    def predecir(self):
        if self.det_idx is None:            # sin detección en el paso anterior: no extrapolar el tamaño
            self.media[7] = 0.0
        self.media, self.cov = self.kf.predecir(self.media, self.cov)

    def corregir(self, caja, score, t, idx):
        self.media, self.cov = self.kf.corregir(self.media, self.cov, xyxy_a_xyah(caja))
        self.score = float(score)
        self.aciertos += 1
        self.t_visto = float(t)
        self.det_idx = idx


class ByteTrackLigero:
    """Seguidor multi-persona estilo ByteTrack (implementación ligera en Python puro)."""

    def __init__(self, umbral_alto=0.5, umbral_bajo=0.1, iou_minimo=0.2, max_perdido_s=1.5,
                 cuadros_para_confirmar=2):
        self.umbral_alto = umbral_alto
        self.umbral_bajo = umbral_bajo
        self.iou_minimo = iou_minimo
        self.max_perdido_s = max_perdido_s
        self.confirmar = cuadros_para_confirmar
        self.kf = FiltroKalmanCaja()
        self.pistas = []
        self._siguiente_id = 1

    @classmethod
    def desde_config(cls, c):
        return cls(c["umbral_alto"], c["umbral_bajo"], c["iou_minimo"], c["max_perdido_s"],
                   c["cuadros_para_confirmar"])

    def _asociar(self, pistas, cajas, idx_det):
        if not pistas or len(idx_det) == 0:
            return [], list(range(len(pistas))), list(idx_det)
        iou = iou_matriz([p.caja for p in pistas], cajas[idx_det])
        filas, cols = linear_sum_assignment(1 - iou)
        pares, usadas_p, usadas_d = [], set(), set()
        for r, c in zip(filas, cols):
            if iou[r, c] >= self.iou_minimo:
                pares.append((r, idx_det[c]))
                usadas_p.add(r)
                usadas_d.add(idx_det[c])
        libres_p = [i for i in range(len(pistas)) if i not in usadas_p]
        libres_d = [d for d in idx_det if d not in usadas_d]
        return pares, libres_p, libres_d

    def _asociar_por_centro(self, pistas, cajas, idx_det, factor=0.6):
        if not pistas or not idx_det:
            return []
        cp = np.array([[(p.caja[0] + p.caja[2]) / 2, (p.caja[1] + p.caja[3]) / 2] for p in pistas])
        cd = np.array([[(cajas[d][0] + cajas[d][2]) / 2, (cajas[d][1] + cajas[d][3]) / 2] for d in idx_det])
        escala = np.array([max(p.caja[3] - p.caja[1], p.caja[2] - p.caja[0]) for p in pistas])
        dist = np.linalg.norm(cp[:, None, :] - cd[None, :, :], axis=2) / np.maximum(escala[:, None], 1.0)
        filas, cols = linear_sum_assignment(dist)
        return [(pistas[r], idx_det[c]) for r, c in zip(filas, cols) if dist[r, c] < factor]

    def actualizar(self, cajas, scores, t):
        """Actualiza con las detecciones del cuadro. Devuelve las pistas confirmadas vistas ahora.

        ``cajas``: (N, 4) en x1, y1, x2, y2; ``scores``: (N,); ``t``: segundos.
        Cada pista devuelta tiene ``det_idx`` = índice de su detección en este cuadro.
        """
        cajas = np.asarray(cajas, float).reshape(-1, 4)
        scores = np.asarray(scores, float).reshape(-1)
        for p in self.pistas:
            p.predecir()
            p.det_idx = None
        altas = [i for i in range(len(cajas)) if scores[i] >= self.umbral_alto]
        bajas = [i for i in range(len(cajas)) if self.umbral_bajo <= scores[i] < self.umbral_alto]
        pares, libres_p, libres_d = self._asociar(self.pistas, cajas, altas)
        for ip, d in pares:
            self.pistas[ip].corregir(cajas[d], scores[d], t, d)
        restantes = [self.pistas[i] for i in libres_p if self.pistas[i].confirmada]
        pares2, _, _ = self._asociar(restantes, cajas, bajas)
        for ip, d in pares2:
            restantes[ip].corregir(cajas[d], scores[d], t, d)
        # Tercera pasada: cambios bruscos de forma (p. ej. una caída: la caja pasa de vertical a horizontal)
        # dejan el IoU bajo; se asocia por cercanía del centro (< 0.6 × la altura de la persona).
        pares3 = self._asociar_por_centro([p for p in self.pistas if p.det_idx is None and p.confirmada],
                                          cajas, [d for d in libres_d if scores[d] >= self.umbral_alto])
        for p, d in pares3:
            p.corregir(cajas[d], scores[d], t, d)
            libres_d.remove(d)
        for d in libres_d:
            nueva = Pista(self._siguiente_id, cajas[d], scores[d], t, self.kf)
            nueva.det_idx = d
            self._siguiente_id += 1
            self.pistas.append(nueva)
        vivas = []
        for p in self.pistas:
            if p.aciertos >= self.confirmar:
                p.confirmada = True
            # Una pista nueva (sin confirmar) se descarta si no reaparece en 0.5 s; una confirmada, tras max_perdido_s.
            limite = self.max_perdido_s if p.confirmada else 0.5
            if p.det_idx is None and t - p.t_visto > limite:
                continue
            vivas.append(p)
        self.pistas = vivas
        return [p for p in self.pistas if p.confirmada and p.det_idx is not None]
