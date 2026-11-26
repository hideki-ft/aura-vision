"""Grabación de sesiones (CSV segundo a segundo) y reporte HTML final.

El CSV servirá como **etiquetas** cuando se conecte una ESP32 real: cada fila
dice qué hacía la persona en ese segundo según la cámara. Las columnas del
Wi-Fi llevan el sufijo ``_calculado`` porque NO son mediciones.
"""

import base64
import csv
import io
import os
import time
from collections import Counter

import numpy as np

COLUMNAS = ["segundo", "tiempo_s", "estado", "confianza_media", "vel_horizontal_ms", "vel_vertical_ms",
            "altura_cadera_m", "pos_x_m", "pos_y_m", "V_calculado", "energia_0p5_20Hz_calculado",
            "movimiento_wifi_calculado", "alerta"]

COLORES = {"de_pie": "#2ecc71", "caminando": "#3498db", "sentado": "#9b59b6", "saltando": "#f1c40f",
           "caida": "#e74c3c", "en_el_suelo": "#e67e22", "incierto": "#95a5a6", "ausente": "#34495e"}


def _media(v):
    v = [x for x in v if x is not None and np.isfinite(x)]
    return round(float(np.mean(v)), 4) if v else ""


class GrabadorSesion:
    """Acumula muestras por segundo y escribe una fila por segundo en ``sesion.csv``."""

    def __init__(self, carpeta_base, notas=None):
        self.carpeta = os.path.join(carpeta_base, time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(self.carpeta, exist_ok=True)
        self.ruta_csv = os.path.join(self.carpeta, "sesion.csv")
        self._f = open(self.ruta_csv, "w", newline="", encoding="utf-8")
        self._w = csv.writer(self._f)
        self._w.writerow(COLUMNAS)
        self.t0 = None
        self.segundo = None
        self.bucket = []
        self.filas = []
        self.eventos = []
        self.alertas = []
        self.notas = notas or {}
        self.cerrada = False

    def agregar(self, t, m):
        """``m``: dict con estado, confianza, vx, vy, h_m, pos, V, energia, movimiento, alerta."""
        if self.cerrada:
            return
        if self.t0 is None:
            self.t0 = t
        seg = int(t - self.t0)
        if self.segundo is not None and seg != self.segundo:
            self._volcar()
        self.segundo = seg
        self.bucket.append(m)

    def evento(self, ev):
        self.eventos.append(ev)

    def alerta(self, al):
        self.alertas.append(al)

    def _volcar(self):
        if not self.bucket:
            return
        b = self.bucket
        estados = Counter(x["estado"] for x in b)
        pos = [x.get("pos") for x in b if x.get("pos") is not None]
        fila = [self.segundo, self.segundo, estados.most_common(1)[0][0], _media([x.get("confianza") for x in b]),
                _media([x.get("vx") for x in b]), _media([x.get("vy") for x in b]), _media([x.get("h_m") for x in b]),
                _media([p[0] for p in pos]), _media([p[1] for p in pos]), _media([x.get("V") for x in b]),
                _media([x.get("energia") for x in b]), int(any(x.get("movimiento") for x in b)),
                next((x["alerta"] for x in reversed(b) if x.get("alerta")), "")]
        self._w.writerow(fila)
        self._f.flush()
        self.filas.append(dict(zip(COLUMNAS, fila)))
        self.bucket = []

    def cerrar(self):
        """Escribe el último segundo, cierra el CSV y genera ``reporte.html``. Devuelve la ruta del reporte."""
        if self.cerrada:
            return os.path.join(self.carpeta, "reporte.html")
        self._volcar()
        self._f.close()
        self.cerrada = True
        ruta = os.path.join(self.carpeta, "reporte.html")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(generar_reporte(self.filas, self.eventos, self.alertas, self.notas))
        return ruta


def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor=fig.get_facecolor())
    import matplotlib.pyplot as plt
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def generar_reporte(filas, eventos, alertas, notas):
    """HTML autocontenido con gráficas (PNG embebidos), tiempo en cada estado, caídas y resumen."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.style.use("dark_background")
    dur = len(filas)
    estados = Counter(f["estado"] for f in filas)
    n_caidas = sum(1 for e in eventos if e.get("tipo") == "caida")
    t = np.array([f["tiempo_s"] for f in filas], float)
    V = np.array([f["V_calculado"] if f["V_calculado"] != "" else np.nan for f in filas], float)
    umbral = notas.get("umbral_V", 10)
    imgs = []
    if dur:
        fig, ax = plt.subplots(2, 1, figsize=(10, 5.2), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})
        for f in filas:
            ax[0].axvspan(f["tiempo_s"], f["tiempo_s"] + 1, color=COLORES.get(f["estado"], "#777"), alpha=0.18, lw=0)
        ax[0].plot(t + 0.5, V, color="#00d4ff", lw=1.6, label="V (CALCULADO)")
        ax[0].axhline(umbral, color="#ff5252", ls="--", lw=1, label=f"umbral {umbral}")
        ax[0].set_ylabel("V (CALCULADO)")
        ax[0].legend(loc="upper right")
        lista = list(COLORES)
        for f in filas:
            ax[1].barh(lista.index(f["estado"]) if f["estado"] in lista else 0, 1, left=f["tiempo_s"],
                       color=COLORES.get(f["estado"], "#777"))
        ax[1].set_yticks(range(len(lista)))
        ax[1].set_yticklabels(lista, fontsize=7)
        ax[1].set_xlabel("tiempo (s)")
        for e in eventos:
            if e.get("tipo") == "caida" and "t_rel" in e:
                for a in ax:
                    a.axvline(e["t_rel"], color="#e74c3c", lw=2)
        imgs.append(("V(t) calculada y estados", _png(fig)))
        fig, ax = plt.subplots(figsize=(7, 3))
        ks = list(estados)
        ax.bar(ks, [estados[k] for k in ks], color=[COLORES.get(k, "#777") for k in ks])
        ax.set_ylabel("segundos")
        ax.set_title("Tiempo en cada estado")
        imgs.append(("Tiempo en cada estado", _png(fig)))
    filas_estado = "".join(f"<tr><td>{k}</td><td>{v} s</td><td>{100 * v / max(dur, 1):.0f} %</td></tr>"
                           for k, v in estados.most_common())
    filas_alerta = "".join(f"<li>{a.get('t_rel', a.get('t', 0)):.1f} s — {a['mensaje']}</li>" for a in alertas) \
        or "<li>Sin alertas</li>"
    vmax = np.nanmax(V) if np.isfinite(V).any() else 0
    seg_mov = int(np.nansum(V > umbral)) if np.isfinite(V).any() else 0
    resumen = (f"Sesión de {dur} s. Estado más frecuente: <b>{estados.most_common(1)[0][0] if estados else '—'}</b>. "
               f"Caídas detectadas: <b>{n_caidas}</b>. Segundos con movimiento Wi-Fi (CALCULADO, V &gt; {umbral}): "
               f"<b>{seg_mov}</b>; V máxima (CALCULADO): <b>{vmax:.1f}</b>.")
    figuras = "".join(f"<h2>{n}</h2><img src='data:image/png;base64,{b}'>" for n, b in imgs)
    info = "".join(f"<li><b>{k}</b>: {v}</li>" for k, v in notas.items())
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Reporte AURA</title>
<style>body{{background:#0f1419;color:#e6e6e6;font-family:system-ui,sans-serif;max-width:980px;margin:auto;padding:16px}}
h1{{color:#00d4ff}} table{{border-collapse:collapse}} td{{border:1px solid #333;padding:4px 10px}}
img{{max-width:100%;border:1px solid #333;border-radius:6px}} .nota{{color:#aaa;font-size:.9em}}
.calc{{background:#1e3a5f;color:#9fd3ff;padding:1px 6px;border-radius:4px;font-size:.8em}}</style></head><body>
<h1>AURA · Reporte de sesión</h1>
<p>{resumen}</p>
<p class="nota">Las cifras Wi-Fi son <span class="calc">CALCULADO</span>: se obtienen con física de ondas a partir
de la posición que ve la cámara; no son mediciones de una ESP32. Las alertas son avisos de bienestar,
no diagnósticos.</p>
{figuras}
<h2>Tiempo en cada estado</h2><table><tr><td><b>Estado</b></td><td><b>Tiempo</b></td><td><b>%</b></td></tr>{filas_estado}</table>
<h2>Alertas</h2><ul>{filas_alerta}</ul>
<h2>Datos de la sesión</h2><ul>{info}</ul>
<p class="nota">CSV segundo a segundo: <code>sesion.csv</code> (en esta misma carpeta).</p>
</body></html>"""
