// AURA · interfaz web. Recibe el estado por WebSocket y dibuja los 6 paneles en <canvas>.
"use strict";

const TOKEN = new URLSearchParams(location.search).get("t") || "";
const COLORES = {
  de_pie: "#2ecc71", caminando: "#3498db", sentado: "#9b59b6", saltando: "#f1c40f",
  caida: "#e74c3c", en_el_suelo: "#e67e22", incierto: "#95a5a6", ausente: "#34495e",
};
const NOMBRES = {
  de_pie: "De pie", caminando: "Caminando", sentado: "Sentado", saltando: "Saltando",
  caida: "Posible caída", en_el_suelo: "En el suelo", incierto: "Incierto", ausente: "Ausente",
};
const ESQUELETO = [[5,6],[5,7],[7,9],[6,8],[8,10],[5,11],[6,12],[11,12],[11,13],[13,15],[12,14],[14,16],[0,1],[0,2],[1,3],[2,4]];
const COLOR_CAMINO = { "directo": "#00d4ff", "cuerpo": "#ff5bd1" };
const $ = (id) => document.getElementById(id);

let estado = null;
let imagen = null;          // último cuadro de video (ImageBitmap/Image)
let urlImagen = null;
let controlMarioneta = false;   // true cuando esta página mueve a la persona sintética
const medidoHist = [];      // [t, V] de la curva MEDIDA (reproducción)

// ------------------------------------------------------------------ conexión
function conectar() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws?t=${encodeURIComponent(TOKEN)}`);
  ws.binaryType = "blob";
  ws.onopen = () => { $("chip-con").textContent = "conectado"; $("chip-con").className = "chip bien"; };
  ws.onclose = () => {
    $("chip-con").textContent = "reconectando…"; $("chip-con").className = "chip malo";
    setTimeout(conectar, 1000);
  };
  ws.onmessage = (ev) => {
    if (typeof ev.data === "string") {
      estado = JSON.parse(ev.data);
      if (estado.medido && estado.medido.V !== null) {
        medidoHist.push([estado.t, estado.medido.V]);
        while (medidoHist.length && medidoHist[0][0] < estado.t - 40) medidoHist.shift();
      }
      requestAnimationFrame(dibujarTodo);
    } else if (!controlMarioneta) {   // con la marioneta se dibuja la escena local, más bonita
      const url = URL.createObjectURL(ev.data);
      const img = new Image();
      img.onload = () => { if (urlImagen) URL.revokeObjectURL(urlImagen); urlImagen = url; imagen = img; };
      img.src = url;
    }
  };
}

async function comando(c) {
  const r = await fetch(`/api/comando?t=${encodeURIComponent(TOKEN)}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(c) });
  const j = await r.json();
  $("msg").textContent = j.mensaje || "";
  return j;
}

// ------------------------------------------------------------------ utilidades de dibujo
function ajustarCanvas(cv) {
  const r = cv.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.round(r.width * dpr), h = Math.round(r.width * (cv.height / cv.width) * dpr);
  if (cv.dataset.w != w) { cv.dataset.h0 = cv.dataset.h0 || cv.height / cv.width; cv.width = w; cv.height = Math.round(w * cv.dataset.h0); cv.dataset.w = w; }
  return cv.getContext("2d");
}
const fmt = (x, d = 2, u = "") => (x === null || x === undefined || Number.isNaN(x)) ? "—" : `${Number(x).toFixed(d)}${u}`;

function ejes(ctx, W, H, m, xmin, xmax, ymin, ymax, etx, ety) {
  ctx.strokeStyle = "#2a3647"; ctx.fillStyle = "#8b98a5"; ctx.lineWidth = 1;
  ctx.font = `${Math.max(10, W / 60)}px system-ui`;
  for (let i = 0; i <= 4; i++) {
    const y = m.t + (H - m.t - m.b) * i / 4;
    ctx.beginPath(); ctx.moveTo(m.l, y); ctx.lineTo(W - m.r, y); ctx.stroke();
    const v = ymax - (ymax - ymin) * i / 4;
    ctx.fillText(ymax < 0.01 ? v.toExponential(0) : v.toFixed(ymax < 1 ? 3 : 0), 2, y + 4);
  }
  ctx.fillText(etx, W - m.r - ctx.measureText(etx).width, H - 4);
  ctx.fillText(ety, m.l + 4, m.t - 4);
}

// ------------------------------------------------------------------ 1. video
function dibujarVideo() {
  const cv = $("cv-video"), ctx = ajustarCanvas(cv), W = cv.width;
  const [iw, ih] = estado.tam || [640, 480];
  const H = Math.round(W * ih / iw);
  if (cv.height !== H) cv.height = H;
  ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W, H);
  if (!estado.privacidad && imagen) ctx.drawImage(imagen, 0, 0, W, H);
  if (estado.privacidad) {
    ctx.fillStyle = "#8b98a5"; ctx.font = `${W / 45}px system-ui`;
    ctx.fillText("MODO PRIVACIDAD: solo esqueleto", 12, H - 12);
  }
  const s = W / iw;
  for (const p of estado.personas || []) {
    const col = p.objetivo ? (COLORES[estado.estado] || "#fff") : "#c8c8c8";
    ctx.lineWidth = p.objetivo ? Math.max(3, W / 200) : 2; ctx.strokeStyle = col; ctx.fillStyle = col;
    for (const [a, b] of ESQUELETO) {
      if (p.scores[a] < 0.3 || p.scores[b] < 0.3) continue;
      ctx.beginPath(); ctx.moveTo(p.kps[a][0] * s, p.kps[a][1] * s); ctx.lineTo(p.kps[b][0] * s, p.kps[b][1] * s); ctx.stroke();
    }
    for (let j = 0; j < 17; j++) if (p.scores[j] >= 0.3) {
      ctx.beginPath(); ctx.arc(p.kps[j][0] * s, p.kps[j][1] * s, ctx.lineWidth + 1, 0, 7); ctx.fill();
    }
    const [x1, y1, x2, y2] = p.caja.map((v) => v * s);
    ctx.lineWidth = 2; ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    ctx.font = `bold ${Math.max(12, W / 50)}px system-ui`;
    const txt = p.objetivo ? `ID ${p.id} · ${NOMBRES[estado.estado] || estado.estado}` : `ID ${p.id}`;
    ctx.fillStyle = "rgba(0,0,0,.6)"; ctx.fillRect(x1, y1 - W / 40 - 6, ctx.measureText(txt).width + 10, W / 40 + 6);
    ctx.fillStyle = col; ctx.fillText(txt, x1 + 5, y1 - 6);
  }
  const cal = estado.calibracion;
  for (const [n, q] of [["A", cal.A_px], ["B", cal.B_px]]) if (q) {
    ctx.fillStyle = "#ffd166"; ctx.beginPath(); ctx.arc(q[0] * s, q[1] * s, 7, 0, 7); ctx.fill();
    ctx.font = "bold 16px system-ui"; ctx.fillText(n, q[0] * s + 9, q[1] * s - 6);
  }
  if (cal.A_px && cal.B_px) {
    ctx.strokeStyle = "#ffd166"; ctx.setLineDash([6, 6]); ctx.beginPath();
    ctx.moveTo(cal.A_px[0] * s, cal.A_px[1] * s); ctx.lineTo(cal.B_px[0] * s, cal.B_px[1] * s); ctx.stroke(); ctx.setLineDash([]);
  }
  ctx.fillStyle = "rgba(0,0,0,.55)"; ctx.fillRect(W - 92, 6, 86, 24);
  ctx.fillStyle = "#fff"; ctx.font = "14px system-ui"; ctx.fillText(`${fmt(estado.fps, 1)} FPS`, W - 86, 23);
  const msg = $("msg-calib");
  if (cal.pendiente) { msg.textContent = `Calibración: haz clic en el punto ${cal.pendiente} del piso.`; msg.classList.remove("oculto"); }
  else msg.classList.add("oculto");
}

// ------------------------------------------------------------------ 2. planta
function dibujarPlanta() {
  const cv = $("cv-planta"), ctx = ajustarCanvas(cv), W = cv.width, H = cv.height, w = estado.wifi;
  ctx.fillStyle = "#05080c"; ctx.fillRect(0, 0, W, H);
  if (!w) return;
  const anchoM = 4.0, largoM = 3.0, m = 20;
  const esc = Math.min((W - 2 * m) / anchoM, (H - 2 * m) / largoM);
  const X = (x) => m + x * esc, Y = (y) => H - m - y * esc;
  ctx.strokeStyle = "#8b98a5"; ctx.lineWidth = 4; ctx.strokeRect(X(0), Y(largoM), anchoM * esc, largoM * esc);
  const amax = Math.max(...w.caminos.map((c) => c.amplitud), 1e-6);
  for (const c of w.caminos) {
    const col = COLOR_CAMINO[c.nombre] || "#7f8c8d";
    ctx.strokeStyle = col; ctx.lineWidth = 1 + 9 * c.amplitud / amax; ctx.globalAlpha = 0.85;
    ctx.setLineDash(c.bloqueado ? [8, 6] : []);
    ctx.beginPath(); c.puntos.forEach((p, i) => (i ? ctx.lineTo(X(p[0]), Y(p[1])) : ctx.moveTo(X(p[0]), Y(p[1])))); ctx.stroke();
  }
  ctx.setLineDash([]); ctx.globalAlpha = 1;
  const T = w.caminos[0].puntos[0], R = w.caminos[0].puntos[1];
  ctx.fillStyle = "#00d4ff"; ctx.fillRect(X(T[0]) - 7, Y(T[1]) - 7, 14, 14);
  ctx.fillStyle = "#2ecc71"; ctx.beginPath(); ctx.arc(X(R[0]), Y(R[1]), 8, 0, 7); ctx.fill();
  ctx.fillStyle = "#e6edf3"; ctx.font = "12px system-ui";
  ctx.fillText("router", X(T[0]) + 10, Y(T[1]) - 10); ctx.fillText("receptor", X(R[0]) + 10, Y(R[1]) - 10);
  if (w.posicion_m) {
    const [px, py] = w.posicion_m;
    ctx.fillStyle = COLORES[estado.estado] || "#fff";
    ctx.beginPath(); ctx.arc(X(px), Y(py), 0.2 * esc, 0, 7); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.fillText("persona", X(px) + 0.22 * esc, Y(py) + 4);
  }
  ctx.fillStyle = "#8b98a5"; ctx.fillText(`${anchoM} × ${largoM} m · ${w.f_central_ghz} GHz · λ = ${w.lambda_m} m · modelo ${w.modelo}`, m, 14);
  $("leyenda-caminos").innerHTML = w.caminos.map((c) =>
    `<span><i style="background:${COLOR_CAMINO[c.nombre] || "#7f8c8d"}"></i>${c.nombre}: d=${c.d.toFixed(2)} m, |a|=${c.amplitud.toFixed(3)}${c.bloqueado ? " (bloqueado)" : ""}</span>`).join("");
}

// ------------------------------------------------------------------ 3. V(t)
function dibujarV() {
  const cv = $("cv-v"), ctx = ajustarCanvas(cv), W = cv.width, H = cv.height;
  ctx.fillStyle = "#05080c"; ctx.fillRect(0, 0, W, H);
  const hist = estado.V_hist || [];
  if (!hist.length) return;
  const tmax = hist[hist.length - 1][0], tmin = tmax - 30;
  const umbral = estado.wifi ? estado.wifi.umbral_V : 10;
  const vmax = Math.max(umbral * 2, ...hist.map((v) => v[1]), ...medidoHist.map((v) => v[1])) * 1.1;
  const m = { l: 34, r: 8, t: 16, b: 18 };
  const X = (t) => m.l + (t - tmin) / 30 * (W - m.l - m.r), Y = (v) => H - m.b - v / vmax * (H - m.t - m.b);
  const lin = estado.linea_estados || [];
  for (let i = 0; i < lin.length - 1; i++) {
    if (lin[i][0] < tmin) continue;
    ctx.fillStyle = COLORES[lin[i][1]] || "#333"; ctx.globalAlpha = 0.18;
    ctx.fillRect(X(lin[i][0]), m.t, X(lin[i + 1][0]) - X(lin[i][0]) + 1, H - m.t - m.b);
  }
  ctx.globalAlpha = 1;
  ejes(ctx, W, H, m, tmin, tmax, 0, vmax, "t (s)", "V");
  ctx.strokeStyle = "#ff5252"; ctx.setLineDash([6, 4]); ctx.beginPath(); ctx.moveTo(m.l, Y(umbral)); ctx.lineTo(W - m.r, Y(umbral)); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = "#ff5252"; ctx.fillText(`umbral ${umbral}`, W - m.r - 70, Y(umbral) - 4);
  const linea = (datos, col, ancho) => {
    ctx.strokeStyle = col; ctx.lineWidth = ancho; ctx.beginPath(); let ini = false;
    for (const [t, v] of datos) { if (t < tmin) continue; ini ? ctx.lineTo(X(t), Y(v)) : ctx.moveTo(X(t), Y(v)); ini = true; }
    ctx.stroke();
  };
  if (medidoHist.length) linea(medidoHist, "#ffc861", 2);
  linea(hist, "#00d4ff", 2.5);
  ctx.font = "bold 13px system-ui"; ctx.fillStyle = "#00d4ff";
  ctx.fillText(`V = ${fmt(estado.wifi && estado.wifi.V, 1)} (CALCULADO)${estado.wifi && estado.wifi.movimiento ? "  → movimiento Wi-Fi (calculado)" : ""}`, m.l + 6, m.t + 14);
  if (estado.medido) { ctx.fillStyle = "#ffc861"; ctx.fillText(`MEDIDO (maqueta): ${fmt(estado.medido.V, 1)} — ${estado.medido.fuente}`, m.l + 6, m.t + 32); }
  $("tag-medido").classList.toggle("oculto", !estado.medido);
}

// ------------------------------------------------------------------ 4. espectro
function dibujarEspectro() {
  const cv = $("cv-esp"), ctx = ajustarCanvas(cv), W = cv.width, H = cv.height, w = estado.wifi;
  ctx.fillStyle = "#05080c"; ctx.fillRect(0, 0, W, H);
  if (!w || !w.espectro_f.length) return;
  const f = w.espectro_f, P = w.espectro_P, fmax = 50;
  const pmax = Math.max(...P, 1e-9) * 1.1;
  const m = { l: 42, r: 8, t: 16, b: 18 };
  const X = (x) => m.l + x / fmax * (W - m.l - m.r), Y = (p) => H - m.b - p / pmax * (H - m.t - m.b);
  const [b0, b1] = w.banda_energia_hz;
  ctx.fillStyle = "rgba(0,212,255,.07)"; ctx.fillRect(X(b0), m.t, X(b1) - X(b0), H - m.t - m.b);
  ejes(ctx, W, H, m, 0, fmax, 0, pmax, "f (Hz)", "densidad");
  ctx.strokeStyle = "#00d4ff"; ctx.lineWidth = 2; ctx.beginPath();
  f.forEach((x, i) => (i ? ctx.lineTo(X(x), Y(P[i])) : ctx.moveTo(X(x), Y(P[i])))); ctx.stroke();
  const marca = (x, col, txt, dash, fila) => {
    if (x === null || x === undefined || x > fmax) return;
    ctx.strokeStyle = col; ctx.setLineDash(dash); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(X(x), m.t); ctx.lineTo(X(x), H - m.b); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = col; ctx.font = "12px system-ui"; ctx.fillText(txt, Math.min(X(x) + 4, W - 150), m.t + 14 * fila);
  };
  marca(w.f_esperada_hz, "#ff5bd1", `2v/λ = ${fmt(w.f_esperada_hz, 1)} Hz`, [6, 4], 1);
  marca(w.f_geometrica_hz, "#ffd166", `geométrica ${fmt(w.f_geometrica_hz, 1)} Hz`, [2, 3], 2);
  marca(w.pico_hz, "#2ecc71", `pico ${fmt(w.pico_hz, 1)} Hz`, [], 3);
}

// ------------------------------------------------------------------ 5. línea de tiempo
function dibujarLinea() {
  const cv = $("cv-linea"), ctx = ajustarCanvas(cv), W = cv.width, H = cv.height;
  ctx.fillStyle = "#05080c"; ctx.fillRect(0, 0, W, H);
  const lin = estado.linea_estados || [];
  if (!lin.length) return;
  const tmax = lin[lin.length - 1][0], tmin = tmax - 60, X = (t) => (t - tmin) / 60 * W;
  for (let i = 0; i < lin.length - 1; i++) {
    if (lin[i + 1][0] < tmin) continue;
    ctx.fillStyle = COLORES[lin[i][1]] || "#333"; ctx.fillRect(X(lin[i][0]), 8, X(lin[i + 1][0]) - X(lin[i][0]) + 1, H - 26);
  }
  for (const a of estado.alertas || []) if (a.t >= tmin) {
    ctx.fillStyle = "#ff5252"; ctx.fillRect(X(a.t) - 1, 0, 3, H - 14);
  }
  ctx.fillStyle = "#8b98a5"; ctx.font = "11px system-ui";
  ctx.fillText("−60 s", 2, H - 3); ctx.fillText("ahora", W - 36, H - 3);
  let x = 60;
  for (const [k, c] of Object.entries(COLORES)) { ctx.fillStyle = c; ctx.fillRect(x, H - 12, 10, 10); ctx.fillStyle = "#8b98a5"; ctx.fillText(k, x + 13, H - 3); x += ctx.measureText(k).width + 26; }
  $("lista-alertas").innerHTML = (estado.alertas || []).slice().reverse().slice(0, 8)
    .map((a) => `<li><b>${a.mensaje}</b> — t = ${a.t.toFixed(1)} s</li>`).join("") || "<li>Sin alertas</li>";
}

// ------------------------------------------------------------------ 6. física
function dibujarFisica() {
  const f = estado.fisica, w = estado.wifi || {};
  const vueltas = (w.delta_fase_rad === null || w.delta_fase_rad === undefined) ? null : w.delta_fase_rad / (2 * Math.PI);
  const salto = f.ultimo_salto;
  const filas = [
    ["Cámara (medida con la cámara)", null],
    ["Altura de la cadera", fmt(f.h_m, 2, " m")],
    ["Velocidad vertical", fmt(f.vy, 2, " m/s")],
    ["Aceleración vertical", fmt(f.ay, 1, " m/s²")],
    ["Velocidad horizontal", fmt(f.vx, 2, " m/s")],
    ["Escala", f.m_por_px ? `1 px = ${(f.m_por_px * 100).toFixed(2)} cm` : "—"],
    ["Último salto", salto ? `${salto.t_vuelo_s} s → ${(salto.altura_m * 100).toFixed(0)} cm` : "—"],
    ["En el suelo tras caída", f.tiempo_en_suelo !== null && f.tiempo_en_suelo !== undefined ? `${f.tiempo_en_suelo} s` : "—"],
    ["Wi-Fi <span class='calc'>CALCULADO</span>", null],
    ["V (σ media × escala)", fmt(w.V, 1)],
    ["Energía 0.5–20 Hz", w.energia_banda !== undefined ? Number(w.energia_banda).toExponential(2) : "—"],
    ["λ", fmt(w.lambda_m, 4, " m")],
    ["v (planta)", fmt(w.velocidad_ms, 2, " m/s")],
    ["f esperada = 2v/λ", fmt(w.f_esperada_hz, 1, " Hz")],
    ["f geométrica (camino real)", fmt(w.f_geometrica_hz, 1, " Hz")],
    ["Pico del espectro", fmt(w.pico_hz, 1, " Hz")],
    ["Δx en 1 s", fmt(w.desplazamiento_1s_m, 3, " m")],
    ["Δφ = 4πΔx/λ", vueltas !== null ? `${w.delta_fase_rad.toFixed(1)} rad (${vueltas.toFixed(1)} vueltas)` : "—"],
    ["|Γ| cuerpo", (w.gamma_cuerpo !== undefined && w.gamma_cuerpo !== null) ? `${w.gamma_cuerpo.toFixed(3)}${w.gamma_cuerpo < 0.01 ? " → ¡invisible para el Wi-Fi!" : ""}` : "—"],
  ];
  if (estado.gcn) filas.push(["ST-GCN++ (opcional)", `${estado.gcn.nombre_top} ${estado.gcn.prob_top}`]);
  $("tabla-fisica").innerHTML = filas.map(([k, v]) => v === null ? `<tr class="seccion"><td colspan="2">${k}</td></tr>` : `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
}

// ------------------------------------------------------------------ general
function dibujarTodo() {
  if (!estado) return;
  $("chip-fps").textContent = `${fmt(estado.fps, 1)} FPS`;
  $("chip-fuente").textContent = estado.fuente.tipo === "video" ? "modo demo (video)" : estado.fuente.tipo === "sintetico" ? "modo sintético" : `cámara ${estado.fuente.valor ?? ""}`;
  $("chip-grab").classList.toggle("oculto", !estado.grabando);
  const e = estado.estado || "ausente";
  $("etiqueta").textContent = NOMBRES[e] || e; $("etiqueta").style.color = COLORES[e] || "#fff";
  $("barra-conf").style.width = `${Math.round(100 * (estado.confianza || 0))}%`;
  $("barra-conf").style.background = COLORES[e] || "#00d4ff";
  $("txt-conf").textContent = `confianza ${Math.round(100 * (estado.confianza || 0))} %`;
  const al = $("alerta");
  if (estado.alerta_activa) { al.textContent = `⚠ ${estado.alerta_activa.toUpperCase()} — alerta de bienestar (no es un diagnóstico)`; al.classList.remove("oculto"); }
  else al.classList.add("oculto");
  const bt = $("bt-grabar");
  bt.textContent = estado.grabando ? "■ Detener y generar reporte" : "● Grabar sesión"; bt.classList.toggle("grabando", estado.grabando);
  if (estado.ultimo_reporte) { const a = $("lnk-reporte"); a.href = `/api/reporte?t=${encodeURIComponent(TOKEN)}`; a.classList.remove("oculto"); }
  if (estado.wifi) $("txt-gamma").textContent = estado.wifi.gamma_cuerpo.toFixed(3);
  if (estado.error) $("msg").textContent = `Aviso del motor: ${estado.error}`;
  dibujarVideo(); dibujarPlanta(); dibujarV(); dibujarEspectro(); dibujarLinea(); dibujarFisica();
}

// ------------------------------------------------------------------ controles
$("cv-video").addEventListener("click", (ev) => {
  const r = ev.target.getBoundingClientRect();
  comando({ accion: "objetivo", x: (ev.clientX - r.left) / r.width, y: (ev.clientY - r.top) / r.height });
});
$("bt-camara").onclick = () => comando({ accion: "camara", valor: Number($("in-camara").value) });
$("bt-estatura").onclick = () => comando({ accion: "estatura", valor: Number($("in-estatura").value) });
$("in-banda").onchange = () => comando({ accion: "banda", valor: $("in-banda").value });
$("bt-umbrales").onclick = async () => {
  await comando({ accion: "umbral_V", valor: Number($("in-umbralv").value) });
  await comando({ accion: "umbral_caida", valor: Number($("in-caida").value) });
  await comando({ accion: "umbral_caminar", valor: Number($("in-caminar").value) });
  $("msg").textContent = "Umbrales aplicados";
};
$("in-contraste").oninput = () => comando({ accion: "contraste", valor: Number($("in-contraste").value) });
$("bt-calibrar").onclick = () => comando({ accion: "calibrar" });
$("bt-calv").onclick = () => comando({ accion: "calibrar_V" });
$("in-priv").onchange = () => comando({ accion: "privacidad", valor: $("in-priv").checked });
$("bt-grabar").onclick = async () => {
  const j = await comando({ accion: "grabar", valor: !(estado && estado.grabando) });
  if (j.reporte) window.open(`/api/reporte?t=${encodeURIComponent(TOKEN)}`, "_blank");
};
$("in-csv").onchange = async () => {
  const f = $("in-csv").files[0]; if (!f) return;
  const r = await fetch(`/api/medido?t=${encodeURIComponent(TOKEN)}`, { method: "POST", headers: { "x-nombre": f.name }, body: f });
  const j = await r.json(); $("msg").textContent = j.mensaje; medidoHist.length = 0;
};
$("bt-qr").onclick = async () => {
  const r = await fetch(`/api/info?t=${encodeURIComponent(TOKEN)}`); const j = await r.json();
  $("img-qr").src = `/api/qr.svg?t=${encodeURIComponent(TOKEN)}`; $("url-qr").textContent = j.url_red || "Solo disponible en esta laptop";
  $("modal-qr").classList.remove("oculto");
};
$("bt-cerrar-qr").onclick = () => $("modal-qr").classList.add("oculto");
fetch(`/api/estado?t=${encodeURIComponent(TOKEN)}`).then((r) => r.json()).then((e) => {
  $("in-estatura").value = e.estatura_m; $("in-priv").checked = e.privacidad;
  if (e.umbrales) { $("in-umbralv").value = e.umbrales.umbral_V; $("in-caida").value = e.umbrales.caida_vel_min_H_s; $("in-caminar").value = e.umbrales.caminar_vel_H_s; }
  if (e.wifi) $("in-banda").value = e.wifi.banda_ghz;
});
conectar();

// ------------------------------------------------------------------ marioneta (modo --sintetico): mover a la persona con el teclado
let marioneta = null;
const lienzoMarioneta = document.createElement("canvas"); lienzoMarioneta.width = 1280; lienzoMarioneta.height = 720;
async function prepararMarioneta() {
  const { Marioneta, ACCIONES } = await import("/static/marioneta.js");
  marioneta = new Marioneta({ estatura: estado.estatura_m || 1.7 });
  $("mando").classList.remove("oculto");
  const tomar = () => {
    if (!controlMarioneta) { controlMarioneta = true; $("mando-titulo").textContent = "🎮 Estás moviendo a la persona (teclado o botones)"; }
  };
  for (const a of ACCIONES) {
    const b = document.createElement("button");
    b.className = "tecla"; b.dataset.accion = a.id;
    b.innerHTML = `<kbd>${a.etiqueta}</kbd><span class="nom">${a.nombre}</span><span class="det">detecta: ${a.detecta}</span>`;
    if (a.mantener) {
      b.addEventListener("pointerdown", (ev) => { ev.preventDefault(); tomar(); marioneta.presionar(a.id); });
      for (const n of ["pointerup", "pointerleave", "pointercancel"]) b.addEventListener(n, () => marioneta.soltar(a.id));
    } else b.addEventListener("click", () => { tomar(); marioneta.presionar(a.id); });
    $("mando-botones").appendChild(b);
  }
  const enCampo = (ev) => ["INPUT", "SELECT", "TEXTAREA"].includes(ev.target.tagName);
  window.addEventListener("keydown", (ev) => {
    if (enCampo(ev)) return;
    const id = marioneta.teclaAAccion(ev.key); if (!id) return;
    ev.preventDefault(); if (ev.repeat) return;
    tomar(); marioneta.presionar(id);
  });
  window.addEventListener("keyup", (ev) => { const id = marioneta.teclaAAccion(ev.key); if (id) marioneta.soltar(id); });
  window.addEventListener("blur", () => ["izquierda", "derecha", "correr", "agacharse"].forEach((a) => marioneta.soltar(a)));
  let tPrev = performance.now();
  setInterval(() => {                         // ~30 veces por segundo: mover, enviar los puntos y dibujar
    if (!controlMarioneta) return;
    const ahora = performance.now(), d = marioneta.actualizar((ahora - tPrev) / 1000); tPrev = ahora;
    fetch(`/api/marioneta?t=${encodeURIComponent(TOKEN)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(d) });
    marioneta.dibujar(lienzoMarioneta.getContext("2d")); imagen = lienzoMarioneta;
    const activa = new Set([...marioneta.teclas, marioneta.ejercicio, marioneta.rutina ? "rutina" : null]);
    document.querySelectorAll(".tecla").forEach((b) => b.classList.toggle("activa", activa.has(b.dataset.accion)));
  }, 33);
}
const esperarSintetico = setInterval(() => {
  if (estado && estado.fuente && estado.fuente.tipo === "sintetico") { clearInterval(esperarSintetico); prepararMarioneta(); }
}, 300);
