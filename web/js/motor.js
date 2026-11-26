// Motor de la versión web: cámara/video → pose → seguimiento → One Euro → reglas → Wi-Fi virtual.
// Equivale a aura/motor.py, pero todo corre en el navegador del visitante.
import { OneEuroFilter } from "./one_euro.js";
import { ClasificadorEstados } from "./clasificador.js";
import { Seguidor } from "./seguimiento.js";
import { Calibracion } from "./calibracion.js";
import { SimuladorWifi, calcularV } from "./wifi.js";
import { cajaDePuntos, mediaPuntos, puntosValidos } from "./esqueleto.js";
import { finito } from "./util.js";

const COLUMNAS = ["segundo", "tiempo_s", "estado", "confianza_media", "vel_horizontal_ms", "vel_vertical_ms", "altura_cadera_m",
  "pos_x_m", "pos_y_m", "V_calculado", "energia_0p5_20Hz_calculado", "movimiento_wifi_calculado", "alerta"];

export class MotorWeb {
  constructor(cfg, opciones) {
    this.cfg = structuredClone(cfg);
    this.op = { detectarCadaS: 0.6, maxPersonas: 2, poseOtrosCada: 2, ...opciones };
    this.estatura = cfg.persona.estatura_m;
    this.privacidad = false;
    this.seguidor = new Seguidor(cfg.seguimiento);
    this.filtros = new Map(); this.ultimos = new Map();
    this.idObjetivo = null; this.idFijado = false; this.tObjVisto = -1e9; this.cajaObj = null;
    this.clasificador = this._nuevoClasificador();
    this.wifi = new SimuladorWifi(cfg.wifi);
    this.calibracion = new Calibracion(cfg.calibracion, cfg.wifi);
    this.linea = []; this.alertas = []; this.eventos = [];
    this.medido = null; this.tMedido = null; this.grabador = null; this.ultimoReporte = null;
    this.fps = 0; this.n = 0; this.estado = { estado: "ausente", confianza: 1 }; this.personas = []; this.wifiEstado = null;
    this.tam = [640, 480]; this.t = 0; this.error = null; this.activo = false; this.tiempos = {};
  }
  _nuevoClasificador() { return new ClasificadorEstados(this.cfg.clasificacion, this.cfg.alertas, this.estatura, this.cfg.pose.umbral_punto); }

  // fuente: { tipo: "camara"|"video"|"sintetico", video?: HTMLVideoElement, rutina?: {...}, estimador?: EstimadorPoseWeb }
  async iniciar(fuente) {
    this.fuente = fuente; this.activo = true; this.t0 = performance.now() / 1000;
    let tPrev = null;
    while (this.activo) {
      try {
        const cuadro = await this._siguienteCuadro();
        if (!cuadro) continue;
        await this._procesar(cuadro);
        const ahora = performance.now() / 1000;
        if (tPrev !== null) { const dt = Math.max(ahora - tPrev, 1e-3); this.fps = this.fps ? 0.9 * this.fps + 0.1 / dt : 1 / dt; }
        tPrev = ahora;
      } catch (err) { this.error = String(err); console.error(err); await new Promise((r) => setTimeout(r, 200)); }
    }
  }
  detener() { this.activo = false; if (this.grabador) this.ultimoReporte = this._cerrarGrabacion(); }

  async _siguienteCuadro() {
    const f = this.fuente;
    if (f.tipo === "sintetico") {
      const r = f.rutina, dur = r.t.length / r.fps, tr = performance.now() / 1000 - this.t0;
      const i = Math.floor((tr % dur) * r.fps), vuelta = Math.floor(tr / dur);
      await new Promise((res) => setTimeout(res, Math.max(0, ((i + 1) / r.fps - (tr % dur)) * 1000)));
      this.tam = [1280, 720];
      return { t: vuelta * dur + r.t[i], extra: { kps: r.kps[i], scores: r.scores[i], caja: r.cajas[i] } };
    }
    const v = f.video;
    await new Promise((res) => (v.requestVideoFrameCallback ? v.requestVideoFrameCallback(() => res()) : requestAnimationFrame(() => res())));
    if (!v.videoWidth) return null;
    this.tam = [v.videoWidth, v.videoHeight];
    let t;
    if (f.tipo === "video") {                    // tiempo del video (correcto aunque el análisis vaya lento)
      if (this._tVidPrev !== undefined && v.currentTime < this._tVidPrev - 0.5) this._offsetVid = (this._offsetVid || 0) + this._tVidPrev;
      this._tVidPrev = v.currentTime; t = (this._offsetVid || 0) + v.currentTime;
    } else t = performance.now() / 1000 - this.t0;
    return { t, fuente: v };
  }

  async _personas(cuadro) {
    const { t } = cuadro;
    if (cuadro.extra) {
      const p = this.seguidor.actualizar([cuadro.extra.caja], t);
      return p.map((q) => ({ id: q.id, caja: cuadro.extra.caja, kps: cuadro.extra.kps, scores: cuadro.extra.scores }));
    }
    const est = this.fuente.estimador, [W, H] = this.tam;
    let cajas;
    const ema = (k, v) => { this.tiempos[k] = this.tiempos[k] ? 0.9 * this.tiempos[k] + 0.1 * v : v; };
    const t0 = performance.now();
    // El detector (lo más lento) corre cada `detectarCadaS` segundos o si no hay a quién seguir / se perdió la pose.
    const perdido = [...this.ultimos.values()].every(([, s]) => s.reduce((a, b) => a + b, 0) / s.length < 0.35);
    if (!this.ultimos.size || perdido || t - (this.tDetector ?? -1e9) >= this.op.detectarCadaS) {
      cajas = await est.detectar(cuadro.fuente, W, H); this.tDetector = t; ema("detector_ms", performance.now() - t0);
    }
    else cajas = [...this.ultimos.values()].map(([k, s]) => cajaDePuntos(k, s)).filter(Boolean);
    let pistas = this.seguidor.actualizar(cajas, t);
    const area = (b) => (b[2] - b[0]) * (b[3] - b[1]);
    pistas.sort((a, b) => (a.id !== this.idObjetivo) - (b.id !== this.idObjetivo) || area(cajas[b.detIdx]) - area(cajas[a.detIdx]));
    pistas = pistas.slice(0, this.op.maxPersonas);
    const turno = this.n % this.op.poseOtrosCada === 0;
    const calc = pistas.filter((p) => p.id === this.idObjetivo || turno || !this.ultimos.has(p.id));
    const t1 = performance.now();
    const res = await est.estimar(cuadro.fuente, calc.map((p) => cajas[p.detIdx]));
    if (calc.length) ema("pose_ms", performance.now() - t1);
    const nuevos = new Map(calc.map((p, j) => [p.id, res[j]]));
    return pistas.map((p) => {
      const r = nuevos.get(p.id) || { kps: this.ultimos.get(p.id)[0], scores: this.ultimos.get(p.id)[1] };
      return { id: p.id, caja: cajas[p.detIdx], kps: r.kps, scores: r.scores };
    });
  }

  async _procesar(cuadro) {
    const { t } = cuadro; this.t = t;
    const personas = await this._personas(cuadro);
    const oe = this.cfg.one_euro, vivos = new Set();
    for (const p of personas) {
      if (!this.filtros.has(p.id)) this.filtros.set(p.id, new OneEuroFilter(oe.min_cutoff, oe.beta, oe.d_cutoff));
      const plano = this.filtros.get(p.id).filtrar(p.kps.flat(), t);
      p.kps = Array.from({ length: 17 }, (_, j) => [plano[2 * j], plano[2 * j + 1]]);
      vivos.add(p.id);
    }
    const idsPistas = new Set(this.seguidor.pistas.map((q) => q.id));
    for (const id of [...this.filtros.keys()]) if (!idsPistas.has(id)) this.filtros.delete(id);
    this.ultimos = new Map(personas.map((p) => [p.id, [p.kps, p.scores]]));

    if (!vivos.has(this.idObjetivo) && personas.length) {
      const suc = this._sucesor(personas, t);
      if (suc) this.idObjetivo = suc.id;                    // el seguidor cambió el ID (p. ej. en una caída)
      else if (!this.idFijado || t - this.tObjVisto > 2) {
        const area = (b) => (b[2] - b[0]) * (b[3] - b[1]);
        const g = personas.reduce((a, b) => (area(b.caja) > area(a.caja) ? b : a));
        if (g.id !== this.idObjetivo) { this.idObjetivo = g.id; this.idFijado = false; this.clasificador.reiniciar(); }
      }
    }
    const obj = personas.find((p) => p.id === this.idObjetivo);
    let est;
    if (obj) { this.tObjVisto = t; this.cajaObj = obj.caja; est = this.clasificador.actualizar(t, obj.kps, obj.scores, obj.caja); }
    else est = this.clasificador.actualizar(t);

    let pos = null;
    if (obj && est.presente) {
      const cad = mediaPuntos(puntosValidos(obj.kps, obj.scores, this.cfg.pose.umbral_punto), [11, 12]);
      pos = this.calibracion.posicion(cad[0], est.suelo_y, est.m_por_px, this.tam[0]);
    }
    const z = pos && finito(est.h_m) ? est.h_m + 0.144 * this.estatura : null;
    this.wifi.alimentar(t, pos, z);
    const wifi = this.wifi.metricas();
    this.n++;
    this._registrar(t, est, wifi, pos);
    this.estado = est; this.wifiEstado = wifi;
    this.personas = personas.map((p) => ({ id: p.id, caja: p.caja, kps: p.kps, scores: p.scores, objetivo: p.id === this.idObjetivo }));
  }

  _sucesor(personas, t) {
    const c = this.cajaObj;
    if (!c || t - this.tObjVisto > 1) return null;
    const cx = (c[0] + c[2]) / 2, cy = (c[1] + c[3]) / 2, tam = Math.max(c[2] - c[0], c[3] - c[1], 1);
    let mejor = null, dmin = 0.6;
    for (const p of personas) {
      const d = Math.hypot((p.caja[0] + p.caja[2]) / 2 - cx, (p.caja[1] + p.caja[3]) / 2 - cy) / tam;
      if (d < dmin) { mejor = p; dmin = d; }
    }
    return mejor;
  }

  _registrar(t, est, wifi, pos) {
    this.linea.push([Math.round(t * 100) / 100, est.estado]);
    while (this.linea.length && this.linea[0][0] < t - 120) this.linea.shift();
    for (const ev of est.eventos || []) { this.eventos.push(ev); if (this.grabador) this.grabador.eventos.push({ ...ev, t_rel: (ev.t_inicio ?? ev.t) - this.grabador.t0 }); }
    for (const al of est.alertas || []) { this.alertas.push(al); if (this.grabador) this.grabador.alertas.push({ ...al, t_rel: al.t - this.grabador.t0 }); }
    if (this.alertas.length > 50) this.alertas.shift();
    if (this.grabador) this._grabar(t, { estado: est.estado, confianza: est.confianza, vx: est.vx, vy: est.vy, h_m: est.h_m, pos,
      V: wifi.V, energia: wifi.energia_banda, movimiento: wifi.movimiento, alerta: est.alerta_activa });
  }

  // ---------------------------------------------------------------- grabación (CSV por segundo + reporte)
  _grabar(t, m) {
    const g = this.grabador;
    if (g.t0 === null) g.t0 = t;
    const seg = Math.floor(t - g.t0);
    if (g.seg !== null && seg !== g.seg) this._volcar();
    g.seg = seg; g.bucket.push(m);
  }
  _volcar() {
    const g = this.grabador, b = g.bucket; if (!b.length) return;
    const med = (v) => { const a = v.filter(finito); return a.length ? Math.round(a.reduce((x, y) => x + y) / a.length * 1e4) / 1e4 : ""; };
    const cuenta = {}; for (const x of b) cuenta[x.estado] = (cuenta[x.estado] || 0) + 1;
    const estado = Object.keys(cuenta).reduce((a, k) => (cuenta[k] > cuenta[a] ? k : a));
    const pos = b.map((x) => x.pos).filter(Boolean);
    g.filas.push([g.seg, g.seg, estado, med(b.map((x) => x.confianza)), med(b.map((x) => x.vx)), med(b.map((x) => x.vy)),
      med(b.map((x) => x.h_m)), med(pos.map((p) => p[0])), med(pos.map((p) => p[1])), med(b.map((x) => x.V)),
      med(b.map((x) => x.energia)), b.some((x) => x.movimiento) ? 1 : 0, ([...b].reverse().find((x) => x.alerta) || {}).alerta || ""]);
    g.bucket = [];
  }
  _cerrarGrabacion() {
    this._volcar();
    const g = this.grabador; this.grabador = null;
    const csv = [COLUMNAS.join(","), ...g.filas.map((f) => f.map((v) => (typeof v === "string" && v.includes(",") ? `"${v}"` : v)).join(","))].join("\n");
    return { csv, filas: g.filas, eventos: g.eventos, alertas: g.alertas, inicio: g.inicio, notas: g.notas };
  }

  // ---------------------------------------------------------------- CSV medido (maqueta)
  cargarMedido(texto, nombre) {
    const lineas = texto.trim().split(/\r?\n/), cab = lineas[0].split(",").map((s) => s.trim());
    const filas = lineas.slice(1).map((l) => l.split(",").map(Number));
    const iT = cab.findIndex((c) => ["tiempo", "t", "time", "tiempo_s", "timestamp", "segundos"].includes(c.toLowerCase()));
    if (iT < 0) throw new Error("El CSV necesita una columna de tiempo (tiempo, t, time, tiempo_s o timestamp)");
    let t = filas.map((f) => f[iT]).filter(finito);
    const dif = t.slice(1).map((x, i) => x - t[i]).sort((a, b) => a - b);
    if (dif.length && dif[dif.length >> 1] > 5) t = t.map((x) => x / 1000);
    t = t.map((x) => x - t[0]);
    const iV = cab.findIndex((c) => c.toLowerCase() === "v");
    let tv, V, tipo;
    if (iV >= 0) { tv = t; V = filas.map((f) => f[iV]); tipo = "V"; }
    else {
      const cols = cab.map((_, i) => i).filter((i) => i !== iT);
      const A = filas.map((f) => cols.map((i) => f[i]));
      const esc = this.cfg.wifi.escala_V_medido ?? 1;
      tv = []; V = [];
      for (let t0 = t[0]; t0 + 1 <= t[t.length - 1] + 1e-9; t0 += 0.1) {
        const sel = A.filter((_, i) => t[i] >= t0 && t[i] < t0 + 1);
        if (sel.length >= 2) { tv.push(t0 + 1); V.push(calcularV(sel, esc)); }
      }
      tipo = `${cols.length} subportadoras`;
    }
    this.medido = { t: tv, V, duracion: tv[tv.length - 1], fuente: nombre, tipo };
    this.tMedido = performance.now() / 1000;
    return `Cargado ${nombre}: ${tipo}, ${this.medido.duracion.toFixed(1)} s (MEDIDO)`;
  }
  _medidoAhora() {
    const m = this.medido; if (!m) return null;
    const tr = (performance.now() / 1000 - this.tMedido) % Math.max(m.duracion, 1e-6);
    let i = m.t.findIndex((x) => x >= tr); if (i <= 0) return m.V[0];
    const u = (tr - m.t[i - 1]) / (m.t[i] - m.t[i - 1]); return m.V[i - 1] + u * (m.V[i] - m.V[i - 1]);
  }

  // ---------------------------------------------------------------- interfaz
  instantanea() {
    const e = this.estado, r = (x, d = 3) => (finito(x) ? Math.round(x * 10 ** d) / 10 ** d : null);
    return {
      t: r(this.t, 2), fps: r(this.fps, 1), fuente: { tipo: this.fuente ? this.fuente.tipo : "—" }, tam: this.tam, privacidad: this.privacidad,
      error: this.error, estado: e.estado, confianza: e.confianza,
      fisica: { h_m: r(e.h_m), vy: r(e.vy), ay: r(e.ay, 2), vx: r(e.vx), torso: r(e.torso, 1), m_por_px: r(e.m_por_px, 5),
        ultimo_salto: e.ultimo_salto || null, tiempo_en_suelo: e.tiempo_en_suelo ?? null },
      puntajes: e.puntajes, alerta_activa: e.alerta_activa || null, id_objetivo: this.idObjetivo, personas: this.personas,
      linea_estados: this.linea.slice(-1500), alertas: this.alertas, eventos: this.eventos.slice(-10), wifi: this.wifiEstado,
      V_hist: this.wifi.historialV(),
      medido: this.medido ? { etiqueta: "MEDIDO (maqueta)", V: this._medidoAhora(), fuente: this.medido.fuente } : null,
      calibracion: this.calibracion.aDict(), estatura_m: this.estatura, grabando: !!this.grabador, ultimo_reporte: this.ultimoReporte ? true : null,
      umbrales: { umbral_V: this.wifi.umbralV, caida_vel_min_H_s: this.cfg.clasificacion.caida_vel_min_H_s, caminar_vel_H_s: this.cfg.clasificacion.caminar_vel_H_s[1] },
      gcn: null, tiempos: Object.fromEntries(Object.entries(this.tiempos).map(([k, v]) => [k, Math.round(v)])),
    };
  }

  comando(c) {
    const acc = c.accion;
    if (acc === "objetivo") {
      const x = c.x * this.tam[0], y = c.y * this.tam[1];
      if (this.calibracion.pendiente) {
        const cual = this.calibracion.pendiente; this.calibracion.fijar(cual, x, y);
        this.calibracion.pendiente = cual === "A" ? "B" : null;
        return { ok: true, mensaje: `Punto ${cual} guardado` + (cual === "A" ? ". Ahora marca el punto B." : ". Calibración lista.") };
      }
      for (const p of this.personas) {
        const [x1, y1, x2, y2] = p.caja;
        if (x >= x1 && x <= x2 && y >= y1 && y <= y2) { this.idObjetivo = p.id; this.idFijado = true; this.clasificador.reiniciar(); return { ok: true, mensaje: `Persona objetivo: ID ${p.id}` }; }
      }
      return { ok: false, mensaje: "No hay ninguna persona en ese punto" };
    }
    if (acc === "calibrar") { this.calibracion.pendiente = "A"; return { ok: true, mensaje: "Haz clic en el punto A del piso y luego en el B" }; }
    if (acc === "estatura") { this.estatura = Math.min(2.3, Math.max(0.8, Number(c.valor))); this.clasificador.estatura = this.estatura; this.clasificador.reiniciar(); return { ok: true, mensaje: `Estatura: ${this.estatura.toFixed(2)} m` }; }
    if (acc === "banda") { this.wifi.fijarBanda(String(c.valor)); return { ok: true, mensaje: `Banda ${c.valor} GHz (λ = ${this.wifi.canal.lam.toFixed(4)} m)` }; }
    if (acc === "contraste") { this.wifi.fijarContraste(Number(c.valor)); return { ok: true, mensaje: `|Γ| cuerpo = ${Math.abs(this.wifi.canal.gammaCuerpo).toFixed(3)}` }; }
    if (acc === "umbral_V") { this.wifi.umbralV = Number(c.valor); return { ok: true, mensaje: `Umbral V = ${c.valor}` }; }
    if (acc === "umbral_caida") { this.cfg.clasificacion.caida_vel_min_H_s = Number(c.valor); return { ok: true, mensaje: "Umbral de caída actualizado" }; }
    if (acc === "umbral_caminar") { const v = Number(c.valor); this.cfg.clasificacion.caminar_vel_H_s = [v / 2, v]; return { ok: true, mensaje: "Umbral de caminar actualizado" }; }
    if (acc === "calibrar_V") { const e = this.wifi.calibrarEscala(); return { ok: true, mensaje: `Escala de V = ${e.toFixed(1)} (persona quieta → V ≈ 5)` }; }
    if (acc === "privacidad") { this.privacidad = !!c.valor; return { ok: true, mensaje: "Modo privacidad " + (this.privacidad ? "activado" : "desactivado") }; }
    if (acc === "grabar") {
      if (c.valor && !this.grabador) {
        this.grabador = { t0: null, seg: null, bucket: [], filas: [], eventos: [], alertas: [], inicio: new Date(),
          notas: { fuente: this.fuente.tipo, estatura_m: this.estatura, banda_GHz: this.wifi.canal.banda, umbral_V: this.wifi.umbralV } };
        return { ok: true, mensaje: "Grabando la sesión (solo números, nunca imágenes)" };
      }
      if (!c.valor && this.grabador) { this.ultimoReporte = this._cerrarGrabacion(); return { ok: true, mensaje: "Sesión guardada", sesion: this.ultimoReporte }; }
      return { ok: true, mensaje: "Sin cambios" };
    }
    return { ok: false, mensaje: `Orden desconocida: ${acc}` };
  }
}
