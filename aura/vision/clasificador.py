"""Clasificación de la actividad en tiempo real con reglas físicas (sin entrenamiento).

En cada cuadro, con los 17 puntos clave ya suavizados:

1. **Escala:** estatura aparente H (px) y línea del suelo → altura de la cadera
   en "alturas de persona" (h) y en metros (h·estatura).
2. **Cinemática SI (causal):** ajuste de una parábola a la altura de la cadera
   de los últimos 0.3 s → velocidad y aceleración vertical; recta a la posición
   horizontal → velocidad horizontal.
3. **Puntajes difusos** de cada postura (de_pie, caminando, sentado, en_el_suelo).
4. **Eventos:** caída (descenso rápido < 1 s que termina en el suelo, confirmado
   ~1 s después) y salto (la cadera sube y los pies dejan el suelo).
5. **Suavizado temporal:** etiqueta más votada en 0.4 s + duración mínima por estado.
6. **Alertas de bienestar** escalonadas según el tiempo en el suelo tras una caída.
"""

from collections import deque

import numpy as np

from .esqueleto import (FRAC_ALTURA_TOBILLO, KP, angulo_en, angulo_torso, estatura_aparente, media_puntos,
                        puntos_validos)

GRAVEDAD = 9.81
POSTURAS = ["de_pie", "caminando", "sentado", "en_el_suelo"]
ERGUIDO = {"de_pie", "caminando", "sentado", "saltando"}
ESTADOS = ["de_pie", "sentado", "caminando", "saltando", "en_el_suelo", "caida", "ausente", "incierto"]


def rampa(x, a, b):
    """0 en ``a``, 1 en ``b``, lineal entre ambos (decreciente si a > b). NaN → 0."""
    if x is None or not np.isfinite(x):
        return 0.0
    if a == b:
        return float(x >= a)
    return float(np.clip((x - a) / (b - a), 0.0, 1.0))


def puntajes_posturas(h, torso, rodilla, aspecto, vx_abs, c):
    """Puntaje (0-1) de cada postura. Fórmulas en el README (sección "Reglas")."""
    erguido = rampa(h, *c["erguido_cadera"]) * rampa(torso, *c["erguido_torso_deg"])
    v0, v1 = c["caminar_vel_H_s"]
    rod = 0.5 if rodilla is None or not np.isfinite(rodilla) else rampa(rodilla, *c["sentado_rodilla_deg"])
    return {
        "de_pie": erguido * rampa(vx_abs, v1, v0),
        "caminando": erguido * rampa(vx_abs, v0, v1),
        "sentado": (rampa(h, *c["sentado_cadera_baja"]) * rampa(h, *c["sentado_cadera_alta"])
                    * rampa(torso, *c["sentado_torso_deg"]) * (0.5 + 0.5 * rod)),
        "en_el_suelo": max(rampa(h, *c["suelo_cadera"]),
                           rampa(h, *c["suelo_cadera_tumbado"]) * max(rampa(torso, *c["suelo_torso_deg"]),
                                                                       rampa(aspecto, *c["suelo_aspecto"]))),
    }


def _mediana(valores):
    v = [x for x in valores if x is not None and np.isfinite(x)]
    return float(np.median(v)) if v else np.nan


def motivo_incierto(piernas, h, s1, s2, conf_kp, c):
    """Por qué el cuadro es "incierto" (texto para la interfaz), o None si no lo es."""
    if not piernas:
        return "no se ven las piernas: aléjate para que la cámara vea el cuerpo completo"
    if conf_kp < c["conf_kp_incierto"]:
        return "puntos del cuerpo poco fiables: mejora la luz o acércate un poco"
    if h is None or not np.isfinite(h):
        return "no se pudo medir la altura de la cadera"
    if s1 < c["puntaje_min"]:
        return "postura no reconocida por las reglas"
    if (s1 - s2) < c["margen_min"]:
        return "dos posturas igual de probables"
    return None


class ClasificadorEstados:
    """Clasificador en línea para UNA persona. Llamar ``actualizar`` en cada cuadro."""

    def __init__(self, cfg_clas, alertas=None, estatura_m=1.70, umbral_punto=0.30):
        self.c = cfg_clas
        self.alertas_cfg = sorted(alertas or [], key=lambda a: a["segundos"])
        self.estatura = float(estatura_m)
        self.umbral_punto = float(umbral_punto)
        self.reiniciar()

    def reiniciar(self):
        self.hist = deque()            # una entrada (dict) por cuadro, últimos ~12 s
        self.buf_H = deque()           # (t, H_px)
        self.buf_tob = deque()         # (t, y del tobillo más bajo estando erguido)
        self.estado_estatico = None
        self.candidato, self.t_candidato = None, 0.0
        self.t_visto = None
        self.caida_pendiente = None
        self.caida_confirmada = None   # dict de la última caída confirmada
        self.t_ultima_caida = -1e9
        self.saltando_hasta = -1e9
        self.en_aire_desde = None
        self.ultimo_salto = None
        self.suelo_desde = None        # inicio del tiempo en el suelo tras una caída
        self.alertas_emitidas = set()
        self.salida = {"estado": "ausente", "confianza": 1.0, "presente": False}

    # ------------------------------------------------------------------ utilidades
    def _ventana(self, t, seg, clave):
        return [e[clave] for e in self.hist if e["t"] >= t - seg]

    def _escala(self, t, xy, caja):
        H_f = estatura_aparente(xy)
        if np.isfinite(H_f):
            self.buf_H.append((t, H_f))
        while self.buf_H and self.buf_H[0][0] < t - 10:
            self.buf_H.popleft()
        if len(self.buf_H) >= 3:
            return float(np.percentile([h for _, h in self.buf_H], 75))
        if np.isfinite(H_f):
            return H_f
        if caja is not None:
            return float(caja[3] - caja[1]) * 0.9
        return np.nan

    def _suelo(self, t, xy, H, torso, cadera, caja):
        tob = np.nanmax([xy[KP["tobillo_izq"], 1], xy[KP["tobillo_der"], 1]]) \
            if np.isfinite(xy[[15, 16], 1]).any() else np.nan
        if np.isfinite(tob) and np.isfinite(torso) and torso < 30 and (tob - cadera[1]) > 0.35 * H:
            self.buf_tob.append((t, tob))
        while self.buf_tob and self.buf_tob[0][0] < t - 10:
            self.buf_tob.popleft()
        if len(self.buf_tob) >= 3:
            y_tob = float(np.median([y for _, y in self.buf_tob]))
        elif np.isfinite(tob):
            y_tob = tob
        elif caja is not None:
            y_tob = float(caja[3]) - FRAC_ALTURA_TOBILLO * H
        else:
            y_tob = np.nan
        return y_tob, y_tob + FRAC_ALTURA_TOBILLO * H, tob

    def _cinematica(self, t):
        """Velocidad/aceleración vertical (parábola) y velocidad horizontal (recta), causales."""
        w = self.c["ventana_cinematica_s"]
        pts = [(e["t"] - t, e["h_m"], e["x_m"]) for e in self.hist
               if e["t"] >= t - w and np.isfinite(e["h_m"])]
        if len(pts) < 2:
            return np.nan, np.nan, np.nan
        tt = np.array([p[0] for p in pts])
        hh = np.array([p[1] for p in pts])
        xx = np.array([p[2] for p in pts])
        if np.ptp(tt) < 1e-3:
            return np.nan, np.nan, np.nan
        if len(pts) >= 4:
            a, b, _ = np.polyfit(tt, hh, 2)
            vy, ay = b, 2 * a
        else:
            vy, ay = np.polyfit(tt, hh, 1)[0], np.nan
        vx = np.polyfit(tt, xx, 1)[0] if np.isfinite(xx).all() else np.nan
        return float(vy), float(ay), float(vx)

    # ------------------------------------------------------------------ principal
    def actualizar(self, t, kps=None, scores=None, caja=None):
        """Procesa un cuadro. ``kps`` (17,2) px, ``scores`` (17,), ``caja`` x1,y1,x2,y2 o None si no hay persona."""
        c = self.c
        eventos, alertas_nuevas = [], []
        if kps is None:
            if self.t_visto is None or t - self.t_visto > c["ausente_tras_s"]:
                est = self._estado_estatico(t, "ausente")
                final = self._estado_final(t, est)
                self._alertas(t, final, alertas_nuevas)
                self.salida = {"estado": final, "confianza": 1.0, "presente": False, "eventos": eventos,
                               "alertas": alertas_nuevas, "alerta_activa": self._alerta_activa(),
                               "tiempo_en_suelo": self._tiempo_suelo(t), "ultimo_salto": self.ultimo_salto}
            else:
                self.salida = dict(self.salida, presente=False, eventos=[], alertas=[])
            return self.salida
        self.t_visto = t
        S = self.estatura
        xy = puntos_validos(kps, scores, self.umbral_punto)
        conf_kp = float(np.mean(scores))
        cadera = media_puntos(xy, [11, 12])
        hombros = media_puntos(xy, [5, 6])
        torso = angulo_torso(cadera, hombros) if np.isfinite(cadera).all() and np.isfinite(hombros).all() else np.nan
        H = self._escala(t, xy, caja)
        y_tob_suelo, suelo, tob = self._suelo(t, xy, H, torso, cadera, caja)
        h_rel = (suelo - cadera[1]) / H if np.isfinite(cadera[1]) and np.isfinite(H) else np.nan
        elev = (y_tob_suelo - tob) / H if np.isfinite(tob) else np.nan
        m_px = S / H if np.isfinite(H) and H > 0 else np.nan
        rod = [angulo_en(xy[KP[f"cadera_{l}"]], xy[KP[f"rodilla_{l}"]], xy[KP[f"tobillo_{l}"]]) for l in ("izq", "der")]
        rod = _mediana(rod)
        aspecto = (caja[3] - caja[1]) / max(caja[2] - caja[0], 1.0) if caja is not None else np.nan
        piernas = int(np.isfinite(xy[[13, 14, 15, 16], 0]).sum()) >= 2

        e = {"t": t, "h_rel": h_rel, "h_m": h_rel * S, "x_m": cadera[0] * m_px if np.isfinite(m_px) else np.nan,
             "torso": torso, "rodilla": rod, "aspecto": aspecto, "elev": elev}
        self.hist.append(e)
        while self.hist and self.hist[0]["t"] < t - 12:
            self.hist.popleft()
        vy, ay, vx = self._cinematica(t)
        e.update(vy_rel=vy / S if np.isfinite(vy) else np.nan, vx_rel=vx / S if np.isfinite(vx) else np.nan)

        w = c["ventana_mediana_s"]
        h_med = _mediana(self._ventana(t, w, "h_rel"))
        torso_med = _mediana(self._ventana(t, w, "torso"))
        rod_med = _mediana(self._ventana(t, w, "rodilla"))
        asp_med = _mediana(self._ventana(t, w, "aspecto"))
        vx_abs = abs(e["vx_rel"]) if np.isfinite(e["vx_rel"]) else np.nan
        P = puntajes_posturas(h_med, torso_med, rod_med, asp_med, vx_abs, c)
        orden = sorted(P, key=P.get, reverse=True)
        s1, s2 = P[orden[0]], P[orden[1]]
        fkp = 0.5 + 0.5 * rampa(conf_kp, c["conf_kp_incierto"], c["conf_kp_buena"])
        conf = s1 * np.sqrt(np.clip((s1 - s2) / 0.3, 0, 1)) * fkp
        motivo = motivo_incierto(piernas, h_med, s1, s2, conf_kp, c)
        if motivo:
            cruda = "incierto"
        else:
            cruda = orden[0]
        e.update(cruda=cruda, conf=float(conf), P=P, fkp=fkp, motivo=motivo)

        est = self._estado_estatico(t, self._moda(t))
        e["estatico"] = est
        self._detectar_caida(t, h_rel, eventos)
        self._detectar_salto(t, h_rel, elev, eventos)
        final = self._estado_final(t, est)
        self._alertas(t, final, alertas_nuevas)

        if final == "caida" and self.caida_confirmada:
            confianza = self.caida_confirmada["confianza"]
        elif final == "saltando":
            confianza = 0.8 * fkp
        elif final == "incierto":
            confianza = min(conf, 0.5)
        elif final == cruda:
            confianza = conf
        elif final in P:
            confianza = 0.7 * P[final] * fkp
        else:
            confianza = 0.5
        self.salida = {
            "estado": final, "confianza": round(float(confianza), 3), "presente": True,
            "h_m": e["h_m"], "h_rel": h_rel, "vy": vy, "ay": ay, "vx": vx, "torso": torso, "rodilla": rod,
            "aspecto": aspecto, "conf_kp": conf_kp, "H_px": H, "m_por_px": m_px, "suelo_y": suelo,
            "piernas_visibles": piernas, "puntajes": {k: round(v, 3) for k, v in P.items()},
            "eventos": eventos, "alertas": alertas_nuevas, "alerta_activa": self._alerta_activa(),
            "tiempo_en_suelo": self._tiempo_suelo(t), "ultimo_salto": self.ultimo_salto,
            "motivo_incierto": motivo if final == "incierto" else None,
        }
        return self.salida

    # ------------------------------------------------------------------ suavizado temporal
    def _moda(self, t):
        votos = self._ventana(t, self.c["ventana_moda_s"], "cruda")
        if not votos:
            return "incierto"
        vals, cnt = np.unique(votos, return_counts=True)
        mejor = vals[np.argmax(cnt)]
        actual = votos[-1]
        return actual if cnt[list(vals).index(actual)] == cnt.max() else str(mejor)

    def _estado_estatico(self, t, candidato):
        """Cambia de estado solo si el candidato se mantiene la duración mínima configurada."""
        if self.estado_estatico is None:
            self.estado_estatico = candidato
        elif candidato == self.estado_estatico:
            self.candidato = None
        else:
            if candidato != self.candidato:
                self.candidato, self.t_candidato = candidato, t
            if t - self.t_candidato >= self.c["duracion_min_s"].get(candidato, 0.4):
                self.estado_estatico, self.candidato = candidato, None
        return self.estado_estatico

    def _estado_final(self, t, est):
        if self.caida_confirmada and t - self.caida_confirmada["t_confirmada"] < self.c["caida_mostrar_s"]:
            return "caida"
        if t < self.saltando_hasta:
            return "saltando"
        return est

    # ------------------------------------------------------------------ eventos
    def _detectar_caida(self, t, h, eventos):
        c = self.c
        hist = list(self.hist)
        if self.caida_pendiente is None and len(hist) >= 2 and t - self.t_ultima_caida > 3.0:
            h_prev = hist[-2]["h_rel"]
            if np.isfinite(h_prev) and np.isfinite(h) and h_prev > c["caida_cadera_final"] >= h:
                # retroceder mientras la cadera bajaba rápido -> inicio del descenso
                i = len(hist) - 1
                while i > 0 and hist[i - 1]["t"] >= t - c["caida_dur_max_s"] - 0.5 and \
                        np.isfinite(hist[i - 1].get("vy_rel", np.nan)) and hist[i - 1]["vy_rel"] < -0.25:
                    i -= 1
                t_ini = hist[max(0, i - 1)]["t"]
                h_ini = np.nanmax([x["h_rel"] for x in hist if t_ini - 0.15 <= x["t"] <= t])
                self.caida_pendiente = {"t_inicio": t_ini, "t_fin": t, "h_inicio": float(h_ini)}
        p = self.caida_pendiente
        if p is None or t - p["t_fin"] < c["caida_confirmar_s"]:
            return
        self.caida_pendiente = None
        tramo = [x for x in hist if x["t"] > p["t_fin"]]
        frac = np.mean([x["cruda"] == "en_el_suelo" for x in tramo]) if tramo else 0.0
        vys = [x["vy_rel"] for x in hist if p["t_inicio"] <= x["t"] <= p["t_fin"] + 0.3 and np.isfinite(x["vy_rel"])]
        pico = -min(vys) if vys else 0.0
        h_fin = np.nanmin([x["h_rel"] for x in hist if x["t"] >= p["t_fin"]] or [np.nan])
        bajada = p["h_inicio"] - h_fin
        dur = p["t_fin"] - p["t_inicio"]
        if (dur <= c["caida_dur_max_s"] and bajada >= c["caida_bajada_min_H"] and pico >= c["caida_vel_min_H_s"]
                and frac >= c["caida_confirmar_frac"]):
            conf = 0.5 + 0.25 * rampa(pico, c["caida_vel_min_H_s"], 2 * c["caida_vel_min_H_s"]) \
                + 0.25 * rampa(frac, c["caida_confirmar_frac"], 1.0)
            ev = {"tipo": "caida", "t_inicio": round(p["t_inicio"], 3), "t_fin": round(p["t_fin"], 3),
                  "t_confirmada": round(t, 3), "duracion_descenso_s": round(dur, 3),
                  "bajada_m": round(bajada * self.estatura, 3), "vel_pico_ms": round(pico * self.estatura, 3),
                  "confianza": round(min(conf, 1.0), 3)}
            self.caida_confirmada = ev
            self.t_ultima_caida = t
            self.suelo_desde = p["t_fin"]
            self.alertas_emitidas = set()
            eventos.append(ev)

    def _detectar_salto(self, t, h, elev, eventos):
        c = self.c
        base = _mediana([x["h_rel"] for x in self.hist if x.get("estatico") in ("de_pie", "caminando")])
        vys = [x["vy_rel"] for x in self.hist if x["t"] >= t - 0.3 and np.isfinite(x.get("vy_rel", np.nan))]
        en_aire = np.isfinite(elev) and elev > c["vuelo_delta_H"]
        if (np.isfinite(base) and np.isfinite(h) and h > base + c["salto_delta_H"] and vys
                and max(vys) >= c["salto_vel_min_H_s"] and (en_aire or not np.isfinite(elev))):
            if t >= self.saltando_hasta:
                eventos.append({"tipo": "salto", "t": round(t, 3)})
            self.saltando_hasta = t + c["salto_mantener_s"]
        # tiempo de vuelo -> altura del salto h = g·t²/8
        if en_aire and self.en_aire_desde is None:
            self.en_aire_desde = t
        elif not en_aire and self.en_aire_desde is not None:
            tv = t - self.en_aire_desde
            self.en_aire_desde = None
            if 0.1 <= tv <= 1.2 and t - self.saltando_hasta < 0.5:
                # Solo vemos el vuelo cuando el tobillo supera δ; en un tiro vertical el tiempo por encima
                # de δ es T_δ² = T² − 8δ/g, así que se corrige: T = √(T_δ² + 8δ/g).
                delta_m = c["vuelo_delta_H"] * self.estatura
                tv = float(np.sqrt(tv ** 2 + 8 * delta_m / GRAVEDAD))
                self.ultimo_salto = {"t": round(t, 2), "t_vuelo_s": round(tv, 3),
                                     "altura_m": round(GRAVEDAD * tv ** 2 / 8, 3)}

    # ------------------------------------------------------------------ alertas
    def _tiempo_suelo(self, t):
        return round(t - self.suelo_desde, 1) if self.suelo_desde is not None else None

    def _alertas(self, t, estado, nuevas):
        if self.suelo_desde is None:
            return
        if estado in ERGUIDO:
            self.suelo_desde = None
            return
        en_suelo = t - self.suelo_desde
        for i, a in enumerate(self.alertas_cfg):
            if en_suelo >= a["segundos"] and i not in self.alertas_emitidas:
                self.alertas_emitidas.add(i)
                nuevas.append({"t": round(t, 2), "nivel": i + 1, "mensaje": a["mensaje"]})

    def _alerta_activa(self):
        if self.suelo_desde is None or not self.alertas_emitidas:
            return None
        return self.alertas_cfg[max(self.alertas_emitidas)]["mensaje"]
