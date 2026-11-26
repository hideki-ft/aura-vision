"""Carga de grabaciones REALES de la maqueta (CSV) para compararlas con lo calculado.

Formatos aceptados (la primera fila son los nombres de las columnas):

* ``tiempo, V``                         → se usa V directamente.
* ``tiempo, sc0, sc1, ..., sc25``       → amplitudes por subportadora; se calcula V
  igual que en la maqueta (σ_k en ventanas de 1 s, promedio, por ``escala``).

La columna de tiempo puede llamarse tiempo, t, time, tiempo_s o timestamp; si
está en milisegundos (pasos > 5) se convierte a segundos. Todo lo que viene de
aquí se etiqueta como "MEDIDO (maqueta)".
"""

import io

import numpy as np
import pandas as pd

from .metricas import serie_V

NOMBRES_TIEMPO = ("tiempo", "t", "time", "tiempo_s", "timestamp", "segundos")


def cargar_csv_medido(datos, escala=1.0, nombre="maqueta.csv"):
    """Lee un CSV (ruta o bytes) y devuelve {'t': [...], 'V': [...], 'duracion_s', 'fuente', 'etiqueta'}."""
    df = pd.read_csv(io.BytesIO(datos)) if isinstance(datos, (bytes, bytearray)) else pd.read_csv(datos)
    cols = {c.strip().lower(): c for c in df.columns}
    col_t = next((cols[n] for n in NOMBRES_TIEMPO if n in cols), None)
    if col_t is None:
        raise ValueError(f"El CSV necesita una columna de tiempo ({', '.join(NOMBRES_TIEMPO)}).")
    t = pd.to_numeric(df[col_t], errors="coerce").to_numpy(float)
    ok = np.isfinite(t)
    df, t = df[ok], t[ok]
    if len(t) < 3:
        raise ValueError("El CSV tiene muy pocas filas.")
    if np.median(np.diff(t)) > 5:      # parece estar en milisegundos
        t = t / 1000.0
    t = t - t[0]
    if "v" in cols:
        V = pd.to_numeric(df[cols["v"]], errors="coerce").to_numpy(float)
        tv, Vv = t, V
        tipo = "V"
    else:
        num = df.drop(columns=[col_t]).apply(pd.to_numeric, errors="coerce")
        num = num.loc[:, num.notna().mean() > 0.9]
        if num.shape[1] == 0:
            raise ValueError("No encontré columnas numéricas de subportadoras ni una columna V.")
        tv, Vv = serie_V(t, num.to_numpy(float), escala=escala)
        tipo = f"{num.shape[1]} subportadoras"
    ok = np.isfinite(Vv)
    return {"t": tv[ok].round(3).tolist(), "V": np.round(Vv[ok], 3).tolist(), "duracion_s": float(tv[ok][-1]),
            "fuente": nombre, "tipo": tipo, "etiqueta": "MEDIDO (maqueta)"}


def valor_en(medido, t_rel):
    """Valor de V medido en el instante relativo ``t_rel`` (reproducción en bucle)."""
    if not medido or not medido["t"]:
        return None
    dur = max(medido["duracion_s"], 1e-6)
    return float(np.interp(t_rel % dur, medido["t"], medido["V"]))
