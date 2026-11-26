"""Opcional (desactivado por defecto): clasificador de esqueleto preentrenado ST-GCN++ (NTU RGB+D 120).

ST-GCN++ es una red de grafos que mira una secuencia de esqueletos (p. ej. 100
cuadros × 17 puntos) y predice una de las 120 acciones de NTU RGB+D 120. Aquí
solo se usa para MOSTRAR una segunda opinión (no cambia las reglas).

Para activarlo hay que exportar el modelo a ONNX (ver README, "Opcional:
ST-GCN++") y poner ``gcn.activado: true`` en config.yaml. Entrada esperada:
(N=1, M personas, T cuadros, V=17 puntos, C=3 [x, y, confianza]).
"""

from collections import deque

import numpy as np


class ClasificadorGCN:
    def __init__(self, cfg_gcn, sesion=None):
        self.cfg = cfg_gcn
        self.T = int(cfg_gcn.get("cuadros", 100))
        self.cada = int(cfg_gcn.get("cada_n_cuadros", 10))
        self.clases = {int(k): v for k, v in (cfg_gcn.get("clases_interes") or {}).items()}
        if sesion is None:
            import onnxruntime as ort
            sesion = ort.InferenceSession(cfg_gcn["modelo_onnx"], providers=["CPUExecutionProvider"])
        self.sesion = sesion
        self.nombre_entrada = self.sesion.get_inputs()[0].name
        forma = self.sesion.get_inputs()[0].shape
        self.M = forma[1] if isinstance(forma[1], int) else 1
        self.buffer = deque(maxlen=self.T)
        self.n = 0
        self.ultimo = None

    def agregar(self, kps, scores):
        """Agrega un esqueleto (normalizado: centrado en la cadera y escalado por su tamaño)."""
        k = np.asarray(kps, float)
        centro = np.nanmean(k[[11, 12]], axis=0)
        escala = max(np.nanmax(k[:, 1]) - np.nanmin(k[:, 1]), 1.0)
        x = np.concatenate([(k - centro) / escala, np.asarray(scores, float)[:, None]], axis=1)
        self.buffer.append(np.nan_to_num(x))
        self.n += 1
        if len(self.buffer) == self.T and self.n % self.cada == 0:
            self.ultimo = self.predecir()
        return self.ultimo

    def predecir(self):
        x = np.zeros((1, self.M, self.T, 17, 3), np.float32)
        x[0, 0] = np.stack(self.buffer)
        logits = np.asarray(self.sesion.run(None, {self.nombre_entrada: x})[0]).reshape(-1)
        p = np.exp(logits - logits.max())
        p /= p.sum()
        top = int(np.argmax(p))
        interes = {self.clases[i]: round(float(p[i]), 3) for i in self.clases if i < len(p)}
        return {"clase_top": top, "nombre_top": self.clases.get(top, f"NTU A{top + 1}"),
                "prob_top": round(float(p[top]), 3), "clases_interes": interes}
