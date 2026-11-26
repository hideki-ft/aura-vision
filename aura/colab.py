"""AURA en Google Colab: la cámara del navegador + el motor de AURA en la GPU de Colab.

1. Un pequeño JavaScript abre la cámara del navegador donde está Colab y muestra el video.
2. Cada cuadro (JPEG reducido) viaja a la máquina de Colab; ahí el MISMO motor de la app de
   escritorio (``aura.motor.Motor``: pose en GPU, seguimiento, One Euro, reglas, Wi-Fi virtual) lo procesa.
3. Vuelve una capa transparente con esqueletos, etiqueta, física y Wi-Fi, que se pinta sobre el video.

Los cuadros viajan solo entre tu navegador y tu máquina virtual de Colab; no se guarda ninguna imagen.
"""

import base64
import time
from collections import deque

import cv2
import numpy as np

from .motor import Motor

COLORES_BGR = {"de_pie": (113, 204, 46), "caminando": (219, 152, 52), "sentado": (182, 89, 155), "saltando": (15, 196, 241),
               "caida": (60, 76, 231), "en_el_suelo": (34, 126, 230), "incierto": (166, 165, 149), "ausente": (94, 73, 52)}
NOMBRES = {"de_pie": "DE PIE", "caminando": "CAMINANDO", "sentado": "SENTADO", "saltando": "SALTANDO",
           "caida": "POSIBLE CAIDA", "en_el_suelo": "EN EL SUELO", "incierto": "INCIERTO", "ausente": "AUSENTE"}
ESQUELETO = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
             (0, 1), (0, 2), (1, 3), (2, 4)]
_CLAVE = np.array([1, 2, 3], np.uint8)       # color "transparente" de la capa

JS_CAMARA = r"""
window.auraIniciar = async function(ancho, frontal) {
  if (window.auraEstado) { window.auraCerrar(); }
  const caja = document.createElement('div');
  caja.style = 'position:relative; display:inline-block; width:100%; max-width:960px; background:#000';
  const video = document.createElement('video');
  video.setAttribute('playsinline', ''); video.muted = true; video.style = 'width:100%; display:block';
  const capa = document.createElement('img');
  capa.style = 'position:absolute; left:0; top:0; width:100%; height:100%; pointer-events:none';
  const boton = document.createElement('button');
  boton.textContent = '⏹ Detener'; boton.style = 'font-size:20px; padding:10px 22px; margin:8px 0';
  const texto = document.createElement('div');
  texto.style = 'font:15px monospace; padding:4px; white-space:pre';
  caja.appendChild(video); caja.appendChild(capa);
  document.body.appendChild(caja); document.body.appendChild(boton); document.body.appendChild(texto);
  const stream = await navigator.mediaDevices.getUserMedia({
      video: {facingMode: frontal ? 'user' : 'environment', width: {ideal: 1280}, height: {ideal: 720}}, audio: false});
  video.srcObject = stream;
  await video.play();
  while (!video.videoWidth) { await new Promise(r => setTimeout(r, 50)); }
  window.auraEstado = {video, capa, boton, texto, stream, ancho, detenido: false, lienzo: document.createElement('canvas')};
  boton.onclick = () => { window.auraEstado.detenido = true; };
  return [video.videoWidth, video.videoHeight];
};
window.auraCuadro = async function(capaUrl, mensaje) {
  const s = window.auraEstado;
  if (!s) { return ''; }
  if (s.detenido) { window.auraCerrar(); return ''; }
  if (capaUrl) { s.capa.src = capaUrl; }
  if (mensaje) { s.texto.textContent = mensaje; }
  const v = s.video, esc = s.ancho / v.videoWidth;
  s.lienzo.width = s.ancho; s.lienzo.height = Math.round(v.videoHeight * esc);
  s.lienzo.getContext('2d').drawImage(v, 0, 0, s.lienzo.width, s.lienzo.height);
  return s.lienzo.toDataURL('image/jpeg', 0.75);
};
window.auraCerrar = function() {
  const s = window.auraEstado;
  if (!s) { return; }
  s.stream.getTracks().forEach(t => t.stop());
  s.boton.disabled = true; s.boton.textContent = 'Cámara detenida';
  window.auraEstado = null;
};
"""


def _texto(img, txt, org, esc, color, grosor=2):
    cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, esc, (0, 0, 0), grosor + 3, cv2.LINE_AA)
    cv2.putText(img, txt, org, cv2.FONT_HERSHEY_SIMPLEX, esc, color, grosor, cv2.LINE_AA)


def _sin_tildes(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")


class SesionColab:
    """Envuelve el motor de AURA para procesar cuadros que llegan desde el navegador."""

    def __init__(self, cfg, estatura_m=1.70):
        from .vision.pose import EstimadorPose
        cfg["persona"]["estatura_m"] = float(estatura_m)
        self.motor = Motor(cfg, {"tipo": "navegador"})
        self.motor.privacidad = True                 # no hace falta recodificar el video: se dibuja una capa
        self.motor.estimador = EstimadorPose(cfg["pose"])
        self.dispositivo = self.motor.estimador.dispositivo
        self.t0 = None
        self._t_prev = None
        self.V = deque(maxlen=300)

    def grabar(self, activar=True):
        """Empieza / termina la grabación (CSV por segundo + reporte HTML en sesiones/)."""
        return self.motor.comando({"accion": "grabar", "valor": bool(activar)})

    def procesar(self, img_bgr, t=None):
        """Procesa un cuadro. Devuelve ``(capa_bgra, datos)``."""
        t = time.monotonic() if t is None else t
        if self.t0 is None:
            self.t0 = t
        if self._t_prev is not None:               # cuadros por segundo reales (incluye el viaje por internet)
            dt = max(t - self._t_prev, 1e-3)
            self.motor.fps = 0.9 * self.motor.fps + 0.1 / dt if self.motor.fps else 1 / dt
        self._t_prev = t
        self.motor._procesar(img_bgr, t - self.t0, None)
        datos, _ = self.motor.instantanea()
        if datos.get("wifi"):
            self.V.append(datos["wifi"]["V"])
        return self.dibujar_capa(img_bgr.shape, datos), datos

    def dibujar_capa(self, forma, d):
        """Capa BGRA: esqueletos, ID, etiqueta grande, confianza, motivo, física, Wi-Fi y alertas."""
        alto, ancho = forma[:2]
        img = np.empty((alto, ancho, 3), np.uint8)
        img[:] = _CLAVE
        est = d.get("estado") or "ausente"
        col = COLORES_BGR.get(est, (255, 255, 255))
        esc = max(0.45, ancho / 1100)
        for p in d.get("personas", []):
            c = col if p["objetivo"] else (210, 210, 210)
            k, s = np.array(p["kps"]), np.array(p["scores"])
            for a, b in ESQUELETO:
                if s[a] >= 0.3 and s[b] >= 0.3:
                    cv2.line(img, tuple(map(int, k[a])), tuple(map(int, k[b])), c, 3 if p["objetivo"] else 2, cv2.LINE_AA)
            for j in range(17):
                if s[j] >= 0.3:
                    cv2.circle(img, tuple(map(int, k[j])), 4, c, -1, cv2.LINE_AA)
            x1, y1, x2, y2 = map(int, p["caja"])
            cv2.rectangle(img, (x1, y1), (x2, y2), c, 2)
            _texto(img, f"ID {p['id']}", (x1 + 4, max(20, y1 - 8)), 0.55 * esc / 0.6, c)
        # panel
        f, w = d.get("fisica") or {}, d.get("wifi") or {}
        lineas = [f"conf {100 * (d.get('confianza') or 0):.0f}%   {d.get('fps', 0):.1f} cuadros/s"]
        if est == "incierto" and d.get("motivo_incierto"):
            lineas.append(_sin_tildes(d["motivo_incierto"])[:60])
        num = lambda v, fmt: "--" if v is None else fmt.format(v)  # noqa: E731
        lineas += [f"cadera {num(f.get('h_m'), '{:.2f}')} m  vy {num(f.get('vy'), '{:+.2f}')} m/s  vx {num(f.get('vx'), '{:+.2f}')}",
                   f"Wi-Fi CALCULADO: V = {num(w.get('V'), '{:.1f}')}{'  -> movimiento' if w.get('movimiento') else ''}",
                   f"2v/lambda = {num(w.get('f_esperada_hz'), '{:.1f}')} Hz   pico {num(w.get('pico_hz'), '{:.1f}')} Hz"]
        alto_panel = int(62 * esc + 26 * esc * len(lineas))
        cv2.rectangle(img, (8, 8), (int(560 * esc), alto_panel), (20, 20, 20), -1)
        _texto(img, NOMBRES.get(est, est), (18, int(50 * esc)), 1.25 * esc, col, 3)
        for i, l in enumerate(lineas):
            _texto(img, l, (18, int(50 * esc + 28 * esc * (i + 1))), 0.55 * esc, (255, 255, 255), 1)
        # mini gráfica de V
        if len(self.V) > 2:
            gx, gy, gw, gh = ancho - int(250 * esc) - 10, 10, int(250 * esc), int(90 * esc)
            cv2.rectangle(img, (gx, gy), (gx + gw, gy + gh), (20, 20, 20), -1)
            vmax = max(25.0, max(self.V))
            umb = w.get("umbral_V", 10)
            yu = int(gy + gh - umb / vmax * gh)
            cv2.line(img, (gx, yu), (gx + gw, yu), (82, 82, 255), 1)
            pts = [(gx + int(i * gw / (len(self.V) - 1)), int(gy + gh - v / vmax * gh)) for i, v in enumerate(self.V)]
            cv2.polylines(img, [np.array(pts, np.int32)], False, (255, 212, 0), 2, cv2.LINE_AA)
            _texto(img, "V(t) CALCULADO", (gx + 6, gy + gh - 6), 0.45 * esc, (255, 255, 255), 1)
        if d.get("alerta_activa"):
            cv2.rectangle(img, (0, alto - int(46 * esc)), (ancho, alto), (40, 40, 200), -1)
            _texto(img, "ALERTA: " + _sin_tildes(d["alerta_activa"]) + " (bienestar, no diagnostico)",
                   (14, alto - int(14 * esc)), 0.75 * esc, (255, 255, 255), 2)
        alfa = np.where(np.all(img == _CLAVE, axis=2), 0, 255).astype(np.uint8)
        alfa[8:alto_panel, 8:int(560 * esc)] = np.maximum(alfa[8:alto_panel, 8:int(560 * esc)], 175)
        return np.dstack([img, alfa])


def _png_url(bgra):
    ok, buf = cv2.imencode(".png", bgra, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _jpeg_a_bgr(url):
    return cv2.imdecode(np.frombuffer(base64.b64decode(url.split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR)


def camara_en_vivo(sesion, duracion_max_s=300, ancho=640, camara_frontal=True, fuente_prueba=None):
    """Abre la cámara del navegador (Colab) y procesa en vivo hasta pulsar "Detener" o ``duracion_max_s``.

    ``fuente_prueba``: ruta de un video para probar sin navegador (pruebas automáticas).
    """
    t_ini, n, capa, msg = time.monotonic(), 0, "", "Iniciando..."
    if fuente_prueba is None:
        from IPython.display import Javascript, display
        from google.colab.output import eval_js
        display(Javascript(JS_CAMARA))
        eval_js(f"auraIniciar({int(ancho)}, {str(bool(camara_frontal)).lower()})")
        print("📷 Cámara en marcha: aléjate 2-3 m para que se vea el cuerpo completo. Pulsa '⏹ Detener' para terminar.")
    else:
        cap = cv2.VideoCapture(fuente_prueba)
    while time.monotonic() - t_ini < duracion_max_s:
        if fuente_prueba is None:
            url = eval_js(f"auraCuadro({capa!r}, {msg!r})")
            if not url:
                break
            img = _jpeg_a_bgr(url)
        else:
            ok, img = cap.read()
            if not ok:
                break
            img = cv2.resize(img, (ancho, int(img.shape[0] * ancho / img.shape[1])))
        if img is None:
            continue
        bgra, d = sesion.procesar(img)
        capa = _png_url(bgra)
        n += 1
        msg = (f"{d['estado']} ({100 * (d['confianza'] or 0):.0f}%)  {d['fps']:.1f} cuadros/s  "
               f"V={d['wifi']['V'] if d.get('wifi') else '--'} (CALCULADO)"
               + (f"  ALERTA: {d['alerta_activa']}" if d.get("alerta_activa") else ""))
    dur = time.monotonic() - t_ini
    print(f"⏹ Terminado: {n} cuadros en {dur:.0f} s (≈{n / max(dur, 1e-6):.1f} cuadros/s, GPU: {sesion.dispositivo}). "
          "No se guardó ninguna imagen.")
    return n
