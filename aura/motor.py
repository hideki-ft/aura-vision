"""Motor de la aplicación: une cámara/video → pose → seguimiento → suavizado → reglas → Wi-Fi virtual.

Corre en un hilo propio. La interfaz web le pide el último estado con
``instantanea()`` y le envía órdenes con ``comando()``.
"""

import threading
import time
from collections import deque

import cv2
import numpy as np

from .sesion import GrabadorSesion
from .vision.calibracion import Calibracion
from .vision.clasificador import ClasificadorEstados
from .vision.esqueleto import caja_de_puntos, media_puntos
from .vision.one_euro import OneEuroFilter
from .vision.seguimiento import ByteTrackLigero
from .wifi_virtual.medido import cargar_csv_medido, valor_en
from .wifi_virtual.simulador import SimuladorWifi


# ---------------------------------------------------------------------------------------- fuentes
class FuenteCamara:
    """Cámara en vivo (OpenCV). Un hilo lee sin parar y solo se procesa el ÚLTIMO cuadro:
    así no se acumula retraso aunque el análisis vaya más lento que la cámara."""

    def __init__(self, indice=0, ancho=1280, alto=720):
        import os
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(int(indice), backend)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.cap.isOpened():
            raise RuntimeError(f"No se pudo abrir la cámara {indice}. Prueba otro índice o el modo demo.")
        self.t0 = time.monotonic()
        self.descripcion = f"cámara {indice}"
        self._cond = threading.Condition()
        self._ultimo = None          # (img, t)
        self._n = 0
        self._leido = 0
        self._activo = True
        self._hilo = threading.Thread(target=self._leer_siempre, daemon=True, name="camara-aura")
        self._hilo.start()

    def _leer_siempre(self):
        fallos = 0
        while self._activo:
            ok, img = self.cap.read()
            if not ok:
                fallos += 1
                time.sleep(0.05)
                if fallos > 100:
                    break
                continue
            fallos = 0
            with self._cond:
                self._ultimo = (img, time.monotonic() - self.t0)
                self._n += 1
                self._cond.notify_all()

    def leer(self):
        with self._cond:
            self._cond.wait_for(lambda: self._n > self._leido or not self._activo, timeout=2.0)
            if self._ultimo is None or self._n == self._leido:
                return False, None, None, None
            self._leido = self._n
            img, t = self._ultimo
        return True, img, t, None

    def cerrar(self):
        self._activo = False
        self._hilo.join(timeout=1.0)
        self.cap.release()


class FuenteVideo:
    """Video pregrabado reproducido a velocidad real (salta cuadros si el procesamiento va lento)."""

    def __init__(self, ruta, repetir=True):
        self.ruta = ruta
        self.cap = cv2.VideoCapture(ruta)
        if not self.cap.isOpened():
            raise RuntimeError(f"No se pudo abrir el video {ruta}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.repetir = repetir
        self.idx = 0
        self.offset = 0.0
        self.t_inicio = time.monotonic()
        self.descripcion = f"video {ruta}"

    def leer(self):
        objetivo = int((time.monotonic() - self.t_inicio) * self.fps)
        if objetivo < self.idx:   # vamos adelantados: esperar
            time.sleep((self.idx - objetivo) / self.fps)
        while self.idx < objetivo:          # vamos atrasados: saltar cuadros sin decodificar
            if not self.cap.grab():
                break
            self.idx += 1
        ok, img = self.cap.read()
        if not ok:
            if not self.repetir:
                return False, None, None, None
            self.offset += self.idx / self.fps
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.idx = 0
            self.t_inicio = time.monotonic()
            ok, img = self.cap.read()
        t = self.offset + self.idx / self.fps
        self.idx += 1
        return ok, img, t, None

    def cerrar(self):
        self.cap.release()


class FuenteSintetica:
    """Persona sintética (sin cámara ni modelos): entrega la imagen y los puntos clave ya calculados.

    Por defecto reproduce una rutina automática. Si la interfaz web envía puntos de la "marioneta"
    (la persona que se mueve con el teclado, ``/api/marioneta``), se usan esos mientras sigan llegando.
    """

    def __init__(self, buzon=None):
        from .sintetico import a_pixeles, rutina_demo
        self.esc = rutina_demo()
        self.T, self.K, self.C, self.B = a_pixeles(self.esc, ruido_px=0.8)
        self.fps = self.esc.fps
        self.t_inicio = time.monotonic()
        self.buzon = buzon if buzon is not None else {}
        self.descripcion = "persona sintética"

    def _marioneta_activa(self):
        return self.buzon.get("t") is not None and time.monotonic() - self.buzon["t"] < 1.0

    def leer(self):
        from .sintetico import dibujar_figura
        if self._marioneta_activa():
            visto = self.buzon.get("n", 0)
            fin = time.monotonic() + 0.1
            while self.buzon.get("n", 0) == visto and time.monotonic() < fin:   # esperar el siguiente cuadro
                time.sleep(0.005)
            k, s, b = self.buzon["datos"]
            return True, dibujar_figura(k), time.monotonic() - self.t_inicio, (k, s, b)
        tr = time.monotonic() - self.t_inicio
        dur = len(self.T) / self.fps
        i = int((tr % dur) * self.fps)
        time.sleep(max(0.0, (i + 1) / self.fps - (tr % dur)))
        return True, dibujar_figura(self.K[i]), time.monotonic() - self.t_inicio, (self.K[i], self.C[i], self.B[i])

    def cerrar(self):
        pass


def crear_fuente(desc, cfg, buzon=None):
    tipo = desc.get("tipo", "camara")
    if tipo == "video":
        return FuenteVideo(desc["valor"], cfg["fuente"].get("repetir_video", True))
    if tipo == "sintetico":
        return FuenteSintetica(buzon)
    return FuenteCamara(desc.get("valor", cfg["fuente"]["camara"]), cfg["fuente"]["ancho"], cfg["fuente"]["alto"])


# ---------------------------------------------------------------------------------------- motor
class Motor:
    def __init__(self, cfg, fuente, estimador=None):
        self.cfg = cfg
        self.fuente_desc = dict(fuente)
        self.estimador = estimador
        self.lock = threading.Lock()
        self.activo = False
        self.hilo = None
        self.error = None
        self.estatura = float(cfg["persona"]["estatura_m"])
        self.privacidad = bool(cfg["interfaz"]["privacidad"])
        self.tracker = ByteTrackLigero.desde_config(cfg["seguimiento"])
        self.filtros = {}
        self.ultimos_kps = {}
        self.id_objetivo = None
        self.id_fijado = False
        self.t_objetivo_visto = -1e9
        self.caja_objetivo = None
        self.clasificador = self._nuevo_clasificador()
        self.wifi = SimuladorWifi(cfg["wifi"])
        self.calibracion = Calibracion(cfg["calibracion"], cfg["wifi"])
        self.buzon_marioneta = {}
        if fuente.get("tipo") == "sintetico" and not self.calibracion.calibrada:
            # geometría conocida de la persona sintética (250 px/m, suelo en y = 650): calibración automática del piso
            self.calibracion.fijar_punto("A", 250.0, 650.0)
            self.calibracion.fijar_punto("B", 1030.0, 650.0)
        self.gcn = None
        if cfg.get("gcn", {}).get("activado"):
            try:
                from .vision.gcn import ClasificadorGCN
                self.gcn = ClasificadorGCN(cfg["gcn"])
            except Exception as e:  # el modelo es opcional
                print(f"⚠️ ST-GCN++ desactivado: {e}")
        self.linea_estados = deque()     # (t, estado)
        self.alertas = deque(maxlen=50)
        self.eventos = deque(maxlen=50)
        self.medido = None
        self.t_medido = None
        self.grabador = None
        self.ultimo_reporte = None
        self.fps = 0.0
        self.n_cuadros = 0
        self.estado = {"estado": "ausente", "confianza": 1.0}
        self.personas = []
        self.jpeg = None
        self.tam = (640, 480)
        self.t = 0.0

    def _nuevo_clasificador(self):
        return ClasificadorEstados(self.cfg["clasificacion"], self.cfg["alertas"], self.estatura,
                                   self.cfg["pose"]["umbral_punto"])

    # ------------------------------------------------------------------ ciclo de vida
    def iniciar(self):
        self.fuente = crear_fuente(self.fuente_desc, self.cfg, self.buzon_marioneta)  # primero la fuente: si falla, avisa rápido
        if self.fuente_desc.get("tipo") != "sintetico" and self.estimador is None:
            from .vision.pose import EstimadorPose
            print("Cargando modelos de pose (la primera vez se descargan, ~70 MB)...")
            self.estimador = EstimadorPose(self.cfg["pose"])
            print(f"Modelos listos: modo {self.estimador.params['modo']}, detector {self.estimador.params['detector']},"
                  f" pose {self.estimador.params['modelo_pose']}, dispositivo {self.estimador.dispositivo}")
        self.activo = True
        self.hilo = threading.Thread(target=self._bucle, daemon=True, name="motor-aura")
        self.hilo.start()

    def detener(self):
        self.activo = False
        if self.hilo:
            self.hilo.join(timeout=3)
        try:
            self.fuente.cerrar()
        except Exception:
            pass
        if self.grabador:
            self.ultimo_reporte = self.grabador.cerrar()
            self.grabador = None
        return self.ultimo_reporte

    def _bucle(self):
        t_prev = None
        while self.activo:
            try:
                ok, img, t, extra = self.fuente.leer()
                if not ok:
                    time.sleep(0.02)
                    continue
                self._procesar(img, t, extra)
                ahora = time.monotonic()
                if t_prev is not None:
                    dt = max(ahora - t_prev, 1e-3)
                    self.fps = 0.9 * self.fps + 0.1 / dt if self.fps else 1 / dt
                t_prev = ahora
            except Exception as e:  # se informa en la interfaz y se sigue
                self.error = f"{type(e).__name__}: {e}"
                import traceback
                traceback.print_exc()
                time.sleep(0.2)

    # ------------------------------------------------------------------ procesamiento de un cuadro
    def _personas_en_cuadro(self, img, t, extra):
        """Lista de dicts {id, caja, kps, scores} de las personas confirmadas en este cuadro."""
        if extra is not None:   # fuente sintética: una persona con puntos ya conocidos
            k, s, b = extra
            pistas = self.tracker.actualizar([b], [0.95], t)
            return [{"id": p.id, "caja": b, "kps": k, "scores": s} for p in pistas]
        est = self.estimador
        if self.n_cuadros % est.detectar_cada == 0 or not self.ultimos_kps:
            cajas, scores = est.detectar(img)
        else:
            cajas = [caja_de_puntos(k, s) for k, s in self.ultimos_kps.values()]
            cajas = [c for c in cajas if c is not None]
            scores = [0.9] * len(cajas)
        pistas = self.tracker.actualizar(np.asarray(cajas).reshape(-1, 4), scores, t)
        # prioridad: la persona objetivo y luego las más grandes
        pistas.sort(key=lambda p: (p.id != self.id_objetivo, -float(np.prod(p.caja[2:] - p.caja[:2]))))
        pistas = pistas[:est.max_personas]
        cajas_pose = [np.asarray(cajas[p.det_idx], float) for p in pistas]
        # La persona objetivo se procesa en cada cuadro; las demás cada ``pose_otros_cada`` cuadros
        # (en los cuadros intermedios se reutiliza su último esqueleto).
        turno = self.n_cuadros % max(1, getattr(est, "pose_otros_cada", 1)) == 0
        calcular = [i for i, p in enumerate(pistas)
                    if p.id == self.id_objetivo or turno or p.id not in self.ultimos_kps]
        kps, sc = est.pose(img, [cajas_pose[i] for i in calcular])
        nuevos = {i: (kps[j], sc[j]) for j, i in enumerate(calcular)}
        out = []
        for i, p in enumerate(pistas):
            k, s = nuevos[i] if i in nuevos else self.ultimos_kps[p.id]
            out.append({"id": p.id, "caja": cajas_pose[i], "kps": k, "scores": s})
        return out

    def _procesar(self, img, t, extra):
        self.t = t
        alto, ancho = img.shape[:2]
        self.tam = (ancho, alto)
        personas = self._personas_en_cuadro(img, t, extra)
        oe = self.cfg["one_euro"]
        vivos = set()
        for p in personas:
            f = self.filtros.setdefault(p["id"], OneEuroFilter(oe["min_cutoff"], oe["beta"], oe["d_cutoff"]))
            p["kps"] = f(p["kps"], t)
            vivos.add(p["id"])
        for i in list(self.filtros):
            if i not in {pp.id for pp in self.tracker.pistas}:
                self.filtros.pop(i, None)
        self.ultimos_kps = {p["id"]: (p["kps"], p["scores"]) for p in personas}

        # persona objetivo: la fijada con un clic, o la más grande
        if self.id_objetivo not in vivos and personas:
            continuidad = self._sucesor_del_objetivo(personas, t)
            if continuidad is not None:
                # el tracker cambió el ID (p. ej. durante una caída): es la misma persona, no se reinicia nada
                self.id_objetivo = continuidad["id"]
            elif not self.id_fijado or t - self.t_objetivo_visto > 2.0:
                grande = max(personas, key=lambda p: float(np.prod(p["caja"][2:] - p["caja"][:2])))
                if grande["id"] != self.id_objetivo:
                    self.id_objetivo = grande["id"]
                    self.id_fijado = False
                    self.clasificador.reiniciar()
        obj = next((p for p in personas if p["id"] == self.id_objetivo), None)
        if obj is not None:
            self.t_objetivo_visto = t
            self.caja_objetivo = np.asarray(obj["caja"], float)
            est = self.clasificador.actualizar(t, obj["kps"], obj["scores"], obj["caja"])
        else:
            est = self.clasificador.actualizar(t)

        # posición en la habitación -> Wi-Fi virtual
        pos = None
        if obj is not None and est.get("presente"):
            xy = obj["kps"].copy()
            xy[np.asarray(obj["scores"]) < self.cfg["pose"]["umbral_punto"]] = np.nan
            cad = media_puntos(xy, [11, 12])
            pos = self.calibracion.posicion(cad[0], est.get("suelo_y", np.nan), est.get("m_por_px", np.nan), ancho)
        z_tronco = est.get("h_m", np.nan) + 0.144 * self.estatura if pos is not None else None  # centro del tronco
        self.wifi.alimentar(t, None if pos is None else pos, z_tronco)
        wifi = self.wifi.metricas()
        gcn = None
        if self.gcn is not None and obj is not None:
            gcn = self.gcn.agregar(obj["kps"], obj["scores"])

        with self.lock:
            self.n_cuadros += 1
            self._registrar(t, est, wifi, pos)
            self.estado = est
            self.wifi_estado = wifi
            self.gcn_estado = gcn
            self.personas = [{"id": int(p["id"]), "caja": [round(float(v), 1) for v in p["caja"]],
                              "kps": np.round(np.nan_to_num(p["kps"], nan=-1), 1).tolist(),
                              "scores": np.round(p["scores"], 2).tolist(), "objetivo": p["id"] == self.id_objetivo}
                             for p in personas]
            self.jpeg = None if self.privacidad else self._codificar(img)

    def _sucesor_del_objetivo(self, personas, t, max_hueco_s=1.0):
        """Si el ID objetivo desapareció hace poco y apareció uno nuevo justo donde estaba, es la misma persona."""
        caja = getattr(self, "caja_objetivo", None)
        if caja is None or t - self.t_objetivo_visto > max_hueco_s:
            return None
        centro = (caja[:2] + caja[2:]) / 2
        tam = max(caja[2] - caja[0], caja[3] - caja[1], 1.0)
        mejor, dmin = None, 0.6
        for p in personas:
            c = (np.asarray(p["caja"][:2]) + np.asarray(p["caja"][2:])) / 2
            d = float(np.linalg.norm(c - centro)) / tam
            if d < dmin:
                mejor, dmin = p, d
        return mejor

    def _codificar(self, img):
        ancho = int(self.cfg["interfaz"]["ancho_video"])
        if img.shape[1] > ancho:
            img = cv2.resize(img, (ancho, int(img.shape[0] * ancho / img.shape[1])), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(self.cfg["interfaz"]["calidad_jpeg"])])
        return buf.tobytes() if ok else None

    def _registrar(self, t, est, wifi, pos):
        self.linea_estados.append((round(t, 2), est["estado"]))
        while self.linea_estados and self.linea_estados[0][0] < t - 120:
            self.linea_estados.popleft()
        for ev in est.get("eventos") or []:
            self.eventos.append(ev)
            if self.grabador:
                self.grabador.evento(dict(ev, t_rel=ev.get("t_inicio", ev.get("t", t)) - (self.grabador.t0 or t)))
        for al in est.get("alertas") or []:
            self.alertas.append(al)
            print(f"🔔 [{al['t']:.1f} s] {al['mensaje']}")
            if self.grabador:
                self.grabador.alerta(dict(al, t_rel=al["t"] - (self.grabador.t0 or t)))
        if self.grabador:
            self.grabador.agregar(t, {"estado": est["estado"], "confianza": est.get("confianza"),
                                      "vx": est.get("vx"), "vy": est.get("vy"), "h_m": est.get("h_m"),
                                      "pos": None if pos is None else [float(pos[0]), float(pos[1])],
                                      "V": wifi["V"], "energia": wifi["energia_banda"],
                                      "movimiento": wifi["movimiento"], "alerta": est.get("alerta_activa")})

    # ------------------------------------------------------------------ interfaz
    def instantanea(self):
        """Estado actual (dict listo para JSON) y el JPEG del cuadro (o None en modo privacidad)."""
        def num(x, d=3):
            return None if x is None or not np.isfinite(x) else round(float(x), d)
        with self.lock:
            est = self.estado
            wifi = getattr(self, "wifi_estado", None)
            medido_V = None
            if self.medido is not None:
                medido_V = valor_en(self.medido, time.monotonic() - self.t_medido)
            datos = {
                "t": round(self.t, 2), "fps": round(self.fps, 1), "fuente": self.fuente_desc,
                "tam": self.tam, "privacidad": self.privacidad, "error": self.error,
                "estado": est.get("estado"), "confianza": est.get("confianza"),
                "fisica": {"h_m": num(est.get("h_m")), "vy": num(est.get("vy")), "ay": num(est.get("ay"), 2),
                           "vx": num(est.get("vx")), "torso": num(est.get("torso"), 1),
                           "m_por_px": num(est.get("m_por_px"), 5), "ultimo_salto": est.get("ultimo_salto"),
                           "tiempo_en_suelo": est.get("tiempo_en_suelo")},
                "puntajes": est.get("puntajes"), "alerta_activa": est.get("alerta_activa"),
                "id_objetivo": self.id_objetivo, "personas": self.personas,
                "linea_estados": list(self.linea_estados)[-1500:], "alertas": list(self.alertas),
                "eventos": list(self.eventos)[-10:], "wifi": wifi, "V_hist": self.wifi.historial_V(),
                "medido": None if self.medido is None else {"etiqueta": "MEDIDO (maqueta)", "V": medido_V,
                                                            "fuente": self.medido["fuente"]},
                "calibracion": self.calibracion.a_dict(), "estatura_m": self.estatura,
                "grabando": self.grabador is not None, "ultimo_reporte": self.ultimo_reporte,
                "umbrales": {"umbral_V": self.wifi.umbral_V,
                             "caida_vel_min_H_s": self.cfg["clasificacion"]["caida_vel_min_H_s"],
                             "caminar_vel_H_s": self.cfg["clasificacion"]["caminar_vel_H_s"][1]},
                "gcn": getattr(self, "gcn_estado", None),
            }
            return datos, self.jpeg

    def comando(self, c):
        """Aplica una orden de la interfaz. Devuelve {'ok': bool, 'mensaje': str, ...}."""
        acc = c.get("accion")
        with self.lock:
            if acc == "objetivo":                      # clic en el video (coordenadas 0-1)
                x, y = float(c["x"]) * self.tam[0], float(c["y"]) * self.tam[1]
                if self.calibracion.pendiente:
                    cual = self.calibracion.pendiente
                    self.calibracion.fijar_punto(cual, x, y)
                    self.calibracion.pendiente = "B" if cual == "A" else None
                    return {"ok": True, "mensaje": f"Punto {cual} guardado" +
                            (". Ahora marca el punto B." if cual == "A" else ". Calibración lista.")}
                for p in self.personas:
                    x1, y1, x2, y2 = p["caja"]
                    if x1 <= x <= x2 and y1 <= y <= y2:
                        self.id_objetivo, self.id_fijado = p["id"], True
                        self.clasificador.reiniciar()
                        return {"ok": True, "mensaje": f"Persona objetivo: ID {p['id']}"}
                return {"ok": False, "mensaje": "No hay ninguna persona en ese punto"}
            if acc == "calibrar":
                self.calibracion.pendiente = "A"
                return {"ok": True, "mensaje": "Haz clic en el punto A del piso y luego en el B"}
            if acc == "estatura":
                self.estatura = float(np.clip(float(c["valor"]), 0.8, 2.3))
                self.clasificador.estatura = self.estatura
                self.clasificador.reiniciar()
                return {"ok": True, "mensaje": f"Estatura: {self.estatura:.2f} m"}
            if acc == "banda":
                self.wifi.fijar_banda(str(c["valor"]))
                return {"ok": True, "mensaje": f"Banda {c['valor']} GHz (λ = {self.wifi.canal.lam:.4f} m)"}
            if acc == "contraste":
                self.wifi.fijar_contraste(float(c["valor"]))
                return {"ok": True, "mensaje": f"|Γ| cuerpo = {abs(self.wifi.canal.gamma_cuerpo):.3f}"}
            if acc == "umbral_V":
                self.wifi.umbral_V = float(c["valor"])
                return {"ok": True, "mensaje": f"Umbral V = {self.wifi.umbral_V:g}"}
            if acc == "umbral_caida":
                self.cfg["clasificacion"]["caida_vel_min_H_s"] = float(c["valor"])
                return {"ok": True, "mensaje": "Umbral de caída actualizado"}
            if acc == "umbral_caminar":
                v = float(c["valor"])
                self.cfg["clasificacion"]["caminar_vel_H_s"] = [v / 2, v]
                return {"ok": True, "mensaje": "Umbral de caminar actualizado"}
            if acc == "calibrar_V":
                e = self.wifi.calibrar_escala()
                return {"ok": True, "mensaje": f"Escala de V = {e:.1f} (persona quieta → V ≈ 5)"}
            if acc == "privacidad":
                self.privacidad = bool(c["valor"])
                return {"ok": True, "mensaje": "Modo privacidad " + ("activado" if self.privacidad else "desactivado")}
            if acc == "grabar":
                if c.get("valor") and self.grabador is None:
                    import os
                    self.grabador = GrabadorSesion(os.path.abspath(self.cfg["carpeta_sesiones"]),
                                                   notas={"fuente": str(self.fuente_desc), "estatura_m": self.estatura,
                                                          "banda_GHz": self.wifi.canal.banda,
                                                          "umbral_V": self.wifi.umbral_V})
                    return {"ok": True, "mensaje": f"Grabando en {self.grabador.carpeta}"}
                if not c.get("valor") and self.grabador is not None:
                    self.ultimo_reporte = self.grabador.cerrar()
                    self.grabador = None
                    return {"ok": True, "mensaje": "Sesión guardada", "reporte": self.ultimo_reporte}
                return {"ok": True, "mensaje": "Sin cambios"}
        if acc == "camara":
            return self.cambiar_fuente({"tipo": "camara", "valor": int(c["valor"])})
        return {"ok": False, "mensaje": f"Orden desconocida: {acc}"}

    def cambiar_fuente(self, desc):
        try:
            nueva = crear_fuente(desc, self.cfg)
        except Exception as e:
            return {"ok": False, "mensaje": str(e)}
        if nueva and desc.get("tipo") != "sintetico" and self.estimador is None:
            from .vision.pose import EstimadorPose
            self.estimador = EstimadorPose(self.cfg["pose"])
        vieja = self.fuente
        self.fuente, self.fuente_desc = nueva, dict(desc)
        vieja.cerrar()
        self.clasificador.reiniciar()
        return {"ok": True, "mensaje": f"Fuente: {nueva.descripcion}"}

    def recibir_marioneta(self, d):
        """Puntos de la marioneta enviados por la interfaz (persona sintética controlada con el teclado)."""
        k = np.asarray(d["kps"], float).reshape(17, 2)
        s = np.asarray(d["scores"], float).reshape(17)
        b = np.asarray(d["caja"], float).reshape(4)
        self.buzon_marioneta.update(t=time.monotonic(), datos=(k, s, b), n=self.buzon_marioneta.get("n", 0) + 1)
        return {"ok": True}

    def cargar_medido(self, datos, nombre="maqueta.csv"):
        m = cargar_csv_medido(datos, escala=float(self.cfg["wifi"].get("escala_V_medido", 1.0)), nombre=nombre)
        with self.lock:
            self.medido, self.t_medido = m, time.monotonic()
        return {"ok": True, "mensaje": f"Cargado {nombre}: {m['tipo']}, {m['duracion_s']:.1f} s (MEDIDO)",
                "medido": {"t": m["t"], "V": m["V"]}}
