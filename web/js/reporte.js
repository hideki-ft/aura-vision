// Reporte HTML de la sesión (versión web): gráficas en <canvas> → PNG embebidos. Todo local.
import { COLORES } from "./dibujo.js";

function grafica(ancho, alto, dibujar) {
  const cv = document.createElement("canvas"); cv.width = ancho; cv.height = alto;
  const c = cv.getContext("2d"); c.fillStyle = "#0b0f14"; c.fillRect(0, 0, ancho, alto); c.font = "13px system-ui";
  dibujar(c); return cv.toDataURL("image/png");
}

export function generarReporte(s) {
  const filas = s.filas, dur = filas.length, umbral = s.notas.umbral_V;
  const cuenta = {}; for (const f of filas) cuenta[f[2]] = (cuenta[f[2]] || 0) + 1;
  const orden = Object.entries(cuenta).sort((a, b) => b[1] - a[1]);
  const V = filas.map((f) => (f[9] === "" ? NaN : f[9]));
  const vmax = Math.max(umbral * 2, ...V.filter(Number.isFinite)) * 1.1;
  const nCaidas = s.eventos.filter((e) => e.tipo === "caida").length;
  const imgV = grafica(1000, 380, (c) => {
    const m = { l: 50, r: 10, t: 20, b: 120 }, W = 1000, H = 380, X = (t) => m.l + t / Math.max(dur, 1) * (W - m.l - m.r);
    const Y = (v) => H - m.b - v / vmax * (H - m.t - m.b);
    filas.forEach((f) => { c.fillStyle = COLORES[f[2]] || "#555"; c.globalAlpha = 0.2; c.fillRect(X(f[0]), m.t, X(1) - X(0) + 1, H - m.t - m.b); });
    c.globalAlpha = 1; c.strokeStyle = "#ff5252"; c.setLineDash([6, 4]); c.beginPath(); c.moveTo(m.l, Y(umbral)); c.lineTo(W - m.r, Y(umbral)); c.stroke(); c.setLineDash([]);
    c.strokeStyle = "#00d4ff"; c.lineWidth = 2; c.beginPath(); V.forEach((v, i) => (i ? c.lineTo(X(i + 0.5), Y(v)) : c.moveTo(X(i + 0.5), Y(v)))); c.stroke();
    c.fillStyle = "#e6edf3"; c.fillText("V (CALCULADO)", m.l + 6, m.t + 14); c.fillStyle = "#ff5252"; c.fillText(`umbral ${umbral}`, W - 100, Y(umbral) - 4);
    const estados = Object.keys(COLORES);
    filas.forEach((f) => { const k = estados.indexOf(f[2]); c.fillStyle = COLORES[f[2]] || "#555"; c.fillRect(X(f[0]), H - m.b + 18 + k * 11, X(1) - X(0) + 1, 9); });
    c.fillStyle = "#8b98a5"; estados.forEach((e, k) => c.fillText(e, 2, H - m.b + 27 + k * 11));
    c.fillText("tiempo (s) →", W - 90, H - 2);
  });
  const imgB = grafica(700, 280, (c) => {
    const n = orden.length, bw = 560 / Math.max(n, 1), max = Math.max(1, ...orden.map((o) => o[1]));
    orden.forEach(([e, v], i) => { const h = v / max * 200; c.fillStyle = COLORES[e] || "#777"; c.fillRect(80 + i * bw, 240 - h, bw * 0.7, h); c.fillStyle = "#e6edf3"; c.fillText(e, 80 + i * bw, 258); c.fillText(`${v} s`, 80 + i * bw, 236 - h); });
  });
  const tabla = orden.map(([e, v]) => `<tr><td>${e}</td><td>${v} s</td><td>${(100 * v / Math.max(dur, 1)).toFixed(0)} %</td></tr>`).join("");
  const alertas = s.alertas.map((a) => `<li>${a.t_rel.toFixed(1)} s — ${a.mensaje}</li>`).join("") || "<li>Sin alertas</li>";
  const segMov = V.filter((v) => v > umbral).length;
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Reporte AURA</title>
<style>body{background:#0f1419;color:#e6e6e6;font-family:system-ui,sans-serif;max-width:1000px;margin:auto;padding:16px}h1{color:#00d4ff}
td{border:1px solid #333;padding:4px 10px}table{border-collapse:collapse}img{max-width:100%;border:1px solid #333;border-radius:6px}
.calc{background:#1e3a5f;color:#9fd3ff;padding:1px 6px;border-radius:4px;font-size:.8em}.nota{color:#aaa;font-size:.9em}</style></head><body>
<h1>AURA · Reporte de sesión</h1>
<p>Sesión de ${dur} s (${s.inicio.toLocaleString("es")}). Estado más frecuente: <b>${orden.length ? orden[0][0] : "—"}</b>.
Caídas detectadas: <b>${nCaidas}</b>. Segundos con movimiento Wi-Fi (CALCULADO, V &gt; ${umbral}): <b>${segMov}</b>.</p>
<p class="nota">Las cifras Wi-Fi son <span class="calc">CALCULADO</span> con física de ondas a partir de la cámara; no son mediciones de una ESP32.
Las alertas son avisos de bienestar, no diagnósticos.</p>
<h2>V(t) calculada y estados</h2><img src="${imgV}"><h2>Tiempo en cada estado</h2><img src="${imgB}">
<table><tr><td><b>Estado</b></td><td><b>Tiempo</b></td><td><b>%</b></td></tr>${tabla}</table>
<h2>Alertas</h2><ul>${alertas}</ul>
<h2>Datos</h2><ul>${Object.entries(s.notas).map(([k, v]) => `<li><b>${k}</b>: ${v}</li>`).join("")}</ul>
<p class="nota">El CSV segundo a segundo se descargó como <code>sesion.csv</code>. Generado en el navegador (versión web de AURA).</p></body></html>`;
}
