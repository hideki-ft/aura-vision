// Interfaz de la versión web: pantalla de inicio, bucle de dibujo y controles.
import { MotorWeb } from "./motor.js";
import { EstimadorPoseWeb } from "./pose.js";
import { fijarEstado, dibujarTodo, medidoHist } from "./dibujo.js";
import { generarReporte } from "./reporte.js";
import { Marioneta, ACCIONES } from "./marioneta.js";

const $ = (id) => document.getElementById(id);
const video = $("video");
const esMovil = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
let cfg = null, motor = null, imagen = null, estimador = null, corriendo = false, urlReporte = null, marioneta = null;
const lienzoMarioneta = document.createElement("canvas"); lienzoMarioneta.width = 1280; lienzoMarioneta.height = 720;
$("in-modelo").value = esMovil ? "rapido" : "preciso";
$("in-facing").value = esMovil ? "environment" : "user";

const progreso = (t) => { $("progreso").textContent = t; };
const msg = (t) => { $("msg").textContent = t || ""; };

async function abrirCamara(facing) {
  if (video.srcObject) video.srcObject.getTracks().forEach((t) => t.stop());
  const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
  video.srcObject = stream; video.removeAttribute("src"); video.loop = false;
  await video.play();
}

async function iniciar(tipo, archivo = null) {
  try {
    if (!cfg) cfg = await (await fetch("datos/config.json")).json();
    cfg.persona.estatura_m = Number($("in-estatura-ini").value) || 1.7;
    $("in-estatura").value = cfg.persona.estatura_m;
    const rapido = $("in-modelo").value === "rapido";
    const fuente = { tipo };
    if (tipo !== "sintetico") {
      if (!globalThis.ort) throw new Error("No se pudo cargar ONNX Runtime Web (revisa tu conexión a internet).");
      const gpu = $("in-proc").value !== "cpu";
      if (!estimador || estimador.modeloPose !== (rapido ? "rtmpose_s" : "rtmpose_m") || estimador.usaGPU !== gpu) {
        estimador = await EstimadorPoseWeb.crear("modelos/", rapido ? "rtmpose_s" : "rtmpose_m", progreso, gpu);
        estimador.usaGPU = gpu;
      }
      fuente.estimador = estimador; fuente.video = video;
      if (tipo === "camara") { progreso("Pidiendo permiso para la cámara…"); await abrirCamara($("in-facing").value); $("in-camara").value = $("in-facing").value; }
      else { video.srcObject = null; video.src = URL.createObjectURL(archivo); video.loop = true; await video.play(); }
      imagen = video;
    } else {
      marioneta = new Marioneta({ estatura: cfg.persona.estatura_m });
      marioneta.presionar("rutina");                 // empieza sola; cualquier tecla toma el control
      fuente.marioneta = marioneta;
      imagen = lienzoMarioneta;
      if (video.srcObject) video.srcObject.getTracks().forEach((t) => t.stop());
    }
    $("mando").classList.toggle("oculto", tipo !== "sintetico");
    if (motor) motor.detener();
    motor = new MotorWeb(cfg, rapido ? { detectarCadaS: 1.5, maxPersonas: 1, poseOtrosCada: 2 } : { detectarCadaS: 0.6, maxPersonas: 2, poseOtrosCada: 2 });
    motor.iniciar(fuente);
    $("inicio").classList.add("oculto"); progreso("");
    if (!corriendo) { corriendo = true; requestAnimationFrame(bucle); }
    msg(estimador && tipo !== "sintetico" ? `Modelos listos (${estimador.proveedor === "webgpu" ? "GPU (WebGPU)" : "CPU (WebAssembly)"})` : "");
  } catch (err) {
    console.error(err);
    progreso(`⚠️ ${err.message || err}. Prueba "Probar sin cámara" o revisa los permisos de cámara del navegador.`);
  }
}

function bucle() {
  if (motor) {
    const e = motor.instantanea();
    if (e.medido && e.medido.V !== null) {
      medidoHist.push([e.t, e.medido.V]);
      while (medidoHist.length && medidoHist[0][0] < e.t - 40) medidoHist.shift();
    }
    if (marioneta && imagen === lienzoMarioneta) {
      marioneta.dibujar(lienzoMarioneta.getContext("2d"));
      const activa = new Set([...marioneta.teclas, marioneta.ejercicio, marioneta.rutina ? "rutina" : null]);
      document.querySelectorAll(".tecla").forEach((b) => b.classList.toggle("activa", activa.has(b.dataset.accion)));
    }
    fijarEstado(e, imagen);
    dibujarTodo();
    if (urlReporte) { $("lnk-reporte").href = urlReporte; $("lnk-reporte").classList.remove("oculto"); }
    else $("lnk-reporte").classList.add("oculto");
    if (e.tiempos && e.tiempos.pose_ms) $("chip-fps").title = `pose ${e.tiempos.pose_ms} ms · detector ${e.tiempos.detector_ms || "—"} ms`;
    $("chip-fuente").textContent = { camara: "cámara", video: "video", sintetico: "modo sintético" }[e.fuente.tipo] || "—";
  }
  requestAnimationFrame(bucle);
}

function comando(c) { if (!motor) return {}; const r = motor.comando(c); msg(r.mensaje); return r; }

function descargar(nombre, contenido, tipo) {
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([contenido], { type: tipo })); a.download = nombre; a.click();
  return a.href;
}

// ---------------------------------------------------------------- pantalla de inicio
$("bt-ini-camara").onclick = () => iniciar("camara");
$("bt-ini-sint").onclick = () => iniciar("sintetico");
$("in-video").onchange = () => { const f = $("in-video").files[0]; if (f) iniciar("video", f); };
$("bt-salir").onclick = () => { if (motor) motor.detener(); motor = null; marioneta = null; if (video.srcObject) video.srcObject.getTracks().forEach((t) => t.stop()); $("inicio").classList.remove("oculto"); };

// ---------------------------------------------------------------- controles (mismos que la app de escritorio)
$("cv-video").addEventListener("click", (ev) => {
  const r = ev.target.getBoundingClientRect();
  comando({ accion: "objetivo", x: (ev.clientX - r.left) / r.width, y: (ev.clientY - r.top) / r.height });
});
$("bt-camara").onclick = async () => {
  if (!motor || motor.fuente.tipo !== "camara") { msg("Solo disponible con la cámara"); return; }
  try { await abrirCamara($("in-camara").value); motor.clasificador.reiniciar(); msg("Cámara cambiada"); } catch (e) { msg(String(e)); }
};
$("bt-estatura").onclick = () => comando({ accion: "estatura", valor: Number($("in-estatura").value) });
$("in-banda").onchange = () => comando({ accion: "banda", valor: $("in-banda").value });
$("bt-umbrales").onclick = () => {
  comando({ accion: "umbral_V", valor: Number($("in-umbralv").value) });
  comando({ accion: "umbral_caida", valor: Number($("in-caida").value) });
  comando({ accion: "umbral_caminar", valor: Number($("in-caminar").value) });
  msg("Umbrales aplicados");
};
$("in-contraste").oninput = () => comando({ accion: "contraste", valor: Number($("in-contraste").value) });
$("bt-calibrar").onclick = () => comando({ accion: "calibrar" });
$("bt-calv").onclick = () => comando({ accion: "calibrar_V" });
$("in-priv").onchange = () => comando({ accion: "privacidad", valor: $("in-priv").checked });
$("bt-grabar").onclick = () => {
  const r = comando({ accion: "grabar", valor: !(motor && motor.grabador) });
  if (r.sesion) {
    descargar("sesion.csv", r.sesion.csv, "text/csv");
    urlReporte = URL.createObjectURL(new Blob([generarReporte(r.sesion)], { type: "text/html" }));
    window.open(urlReporte, "_blank");
  }
};
$("in-csv").onchange = async () => {
  const f = $("in-csv").files[0]; if (!f || !motor) return;
  try { msg(motor.cargarMedido(await f.text(), f.name)); medidoHist.length = 0; } catch (e) { msg(`No se pudo leer el CSV: ${e.message}`); }
};
$("bt-qr").onclick = () => {
  const url = location.href.split("#")[0];
  if (globalThis.qrcode) { const q = qrcode(0, "M"); q.addData(url); q.make(); $("img-qr").src = q.createDataURL(6, 8); }
  $("url-qr").textContent = url; $("modal-qr").classList.remove("oculto");
};
$("bt-cerrar-qr").onclick = () => $("modal-qr").classList.add("oculto");

// ---------------------------------------------------------------- mando de la marioneta (teclado + botones táctiles)
for (const a of ACCIONES) {
  const b = document.createElement("button");
  b.className = "tecla"; b.dataset.accion = a.id;
  b.innerHTML = `<kbd>${a.etiqueta}</kbd><span class="nom">${a.nombre}</span><span class="det">detecta: ${a.detecta}</span>`;
  if (a.mantener) {
    b.addEventListener("pointerdown", (ev) => { ev.preventDefault(); marioneta && marioneta.presionar(a.id); });
    for (const evn of ["pointerup", "pointerleave", "pointercancel"]) b.addEventListener(evn, () => marioneta && marioneta.soltar(a.id));
  } else b.addEventListener("click", () => marioneta && marioneta.presionar(a.id));
  $("mando-botones").appendChild(b);
}
const enCampo = (ev) => ["INPUT", "SELECT", "TEXTAREA"].includes(ev.target.tagName);
window.addEventListener("keydown", (ev) => {
  if (!marioneta || imagen !== lienzoMarioneta || enCampo(ev)) return;
  const id = marioneta.teclaAAccion(ev.key); if (!id) return;
  ev.preventDefault();
  if (ev.repeat) return;
  marioneta.presionar(id);
});
window.addEventListener("keyup", (ev) => {
  if (!marioneta) return;
  const id = marioneta.teclaAAccion(ev.key); if (id) marioneta.soltar(id);
});
window.addEventListener("blur", () => marioneta && ["izquierda", "derecha", "correr", "agacharse"].forEach((a) => marioneta.soltar(a)));
