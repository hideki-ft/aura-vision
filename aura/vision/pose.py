"""Estimación de pose 2D con rtmlib (RTMPose + detector YOLOX) sobre ONNX Runtime.

* El **detector** (YOLOX) encuentra las cajas de las personas.
* **RTMPose** recibe cada caja y devuelve 17 puntos clave con su confianza.
* Para ir rápido en CPU, el detector solo corre cada ``detectar_cada`` cuadros;
  en los demás se usan cajas derivadas del esqueleto anterior (lo hace el motor).

Los modelos (Apache-2.0, OpenMMLab) se descargan solos la primera vez en
``~/.cache/rtmlib`` (necesita internet una sola vez).
"""

import numpy as np

BASE = "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
DETECTORES = {
    "yolox-tiny": (BASE + "yolox_tiny_8xb8-300e_humanart-6f3252f9.zip", (416, 416)),
    "yolox-m": (BASE + "yolox_m_8xb8-300e_humanart-c2c7a14a.zip", (640, 640)),
    "yolox-x": (BASE + "yolox_x_8xb8-300e_humanart-a39d44ed.zip", (640, 640)),
}
MODELOS_POSE = {
    "rtmpose-s": (BASE + "rtmpose-s_simcc-body7_pt-body7_420e-256x192-acd4a1ef_20230504.zip", (192, 256)),
    "rtmpose-m": (BASE + "rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.zip", (192, 256)),
    "rtmpose-l": (BASE + "rtmpose-l_simcc-body7_pt-body7_420e-256x192-4dba18fc_20230504.zip", (192, 256)),
}


def elegir_dispositivo(pref="auto"):
    """'cuda' si ONNX Runtime tiene CUDA disponible (y se pidió auto/cuda); si no, 'cpu'."""
    if pref == "cpu":
        return "cpu"
    try:
        import onnxruntime as ort
        if "CUDAExecutionProvider" in ort.get_available_providers():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def parametros_modo(cfg_pose):
    """Combina el modo elegido (lightweight/balanced/performance) con los valores explícitos."""
    modo = cfg_pose.get("modo", "balanced")
    if modo not in cfg_pose["modos"]:
        raise ValueError(f"Modo de pose desconocido: {modo} (usa lightweight, balanced o performance)")
    p = dict(cfg_pose["modos"][modo])
    p.setdefault("max_personas", cfg_pose.get("max_personas", 2))
    p["modelo_pose"] = cfg_pose.get("modelo_pose") or p.get("modelo_pose") or "rtmpose-m"
    p["modo"] = modo
    return p


class EstimadorPose:
    """Detector de personas + RTMPose. ``detectar(img)`` -> cajas, ``pose(img, cajas)`` -> puntos."""

    def __init__(self, cfg_pose):
        from rtmlib import RTMPose, YOLOX
        self.params = parametros_modo(cfg_pose)
        self.dispositivo = elegir_dispositivo(cfg_pose.get("dispositivo", "auto"))
        url_d, tam_d = DETECTORES[self.params["detector"]]
        url_p, tam_p = MODELOS_POSE[self.params["modelo_pose"]]
        self.umbral_det = float(cfg_pose.get("umbral_deteccion", 0.45))
        self.detector = YOLOX(url_d, model_input_size=tam_d, score_thr=self.umbral_det, backend="onnxruntime",
                              device=self.dispositivo)
        self.modelo = RTMPose(url_p, model_input_size=tam_p, backend="onnxruntime", device=self.dispositivo)
        self.detectar_cada = int(self.params["detectar_cada"])
        self.max_personas = int(self.params["max_personas"])
        self.pose_otros_cada = int(self.params.get("pose_otros_cada", 1))

    def detectar(self, img):
        """Cajas (N, 4) y puntajes (N,) de personas. rtmlib ya filtra por clase "persona"."""
        cajas = np.asarray(self.detector(img), float).reshape(-1, 4)
        # rtmlib no devuelve puntajes: lo que supera score_thr se trata como detección segura.
        return cajas, np.full(len(cajas), 0.9)

    def pose(self, img, cajas):
        """Puntos clave (N, 17, 2) en píxeles y confianzas (N, 17) para cada caja.

        Todas las personas van en UN solo lote a ONNX Runtime (más rápido que una por una).
        """
        cajas = np.asarray(cajas, float).reshape(-1, 4)
        if len(cajas) == 0:
            return np.zeros((0, 17, 2)), np.zeros((0, 17))
        from rtmlib.tools.pose_estimation.post_processings import get_simcc_maximum
        m = self.modelo
        entradas, centros, escalas = [], [], []
        for caja in cajas:
            x, c, e = m.preprocess(img, caja)
            entradas.append(x.transpose(2, 0, 1))
            centros.append(c)
            escalas.append(e)
        lote = np.ascontiguousarray(np.stack(entradas), dtype=np.float32)
        nombres = [o.name for o in m.session.get_outputs()]
        simcc_x, simcc_y = m.session.run(nombres, {m.session.get_inputs()[0].name: lote})
        locs, scores = get_simcc_maximum(simcc_x, simcc_y)
        centros, escalas = np.array(centros)[:, None, :], np.array(escalas)[:, None, :]
        kps = locs.reshape(len(cajas), 17, 2) / 2.0 / np.array(m.model_input_size) * escalas + centros - escalas / 2
        return kps.astype(float), np.asarray(scores, float).reshape(len(cajas), 17)
