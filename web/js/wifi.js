// Wi-Fi virtual (TODO CALCULADO) — traducción de aura/wifi_virtual/{canal,metricas,simulador}.py
import { finito, polyfit, randn } from "./util.js";

export const C_LUZ = 299792458.0;

export function frecuenciasSubportadoras(fc, n = 26, df = 312.5e3) {
  return Array.from({ length: n }, (_, k) => fc + (k - (n - 1) / 2) * df);
}

function distanciaASegmento(p, a, b) {
  const ab = [b[0] - a[0], b[1] - a[1]];
  const u = Math.min(1, Math.max(0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / Math.max(ab[0] ** 2 + ab[1] ** 2, 1e-12)));
  return Math.hypot(p[0] - (a[0] + u * ab[0]), p[1] - (a[1] + u * ab[1]));
}

export class CanalWifi {
  constructor(w) {
    this.ancho = w.habitacion.ancho_m; this.largo = w.habitacion.largo_m;
    this.T = [...w.router_m]; this.R = [...w.receptor_m];
    this.gammaPared = w.gamma_pared; this.gammaCuerpoNominal = w.gamma_cuerpo;
    this.contraste = w.contraste_cuerpo ?? 1; this.radio = w.radio_cuerpo_m; this.transmision = w.transmision_bloqueo;
    this.alturaAntenas = (w.altura_antenas_m === null || w.altura_antenas_m === undefined) ? null : Number(w.altura_antenas_m);
    this.nSub = w.subportadoras; this.espaciado = w.espaciado_khz * 1e3;
    this.frecuenciasBanda = w.frecuencias_ghz;
    const paredes = { izquierda: ["x", 0], derecha: ["x", this.ancho], inferior: ["y", 0], superior: ["y", this.largo] };
    let min = Infinity;
    for (const [n, [e, v]] of Object.entries(paredes)) {
      const d = Math.abs(this.T[e === "x" ? 0 : 1] - v); if (d < min) { min = d; this.paredRouter = n; }
    }
    this.paredes = Object.fromEntries(Object.entries(paredes).filter(([n]) => n !== this.paredRouter));
    this.fijarBanda(w.banda_ghz);
  }
  get gammaCuerpo() { return this.gammaCuerpoNominal * this.contraste; }

  fijarBanda(banda) {
    const clave = String(banda);
    const fGhz = this.frecuenciasBanda[clave] ?? Number(banda);
    this.banda = clave; this.fCentral = fGhz * 1e9;
    this.freqs = frecuenciasSubportadoras(this.fCentral, this.nSub, this.espaciado);
    this.lam = C_LUZ / this.fCentral;
    this._precalcular();
  }

  _precalcular() {
    this.dDirecto = Math.hypot(this.R[0] - this.T[0], this.R[1] - this.T[1]);
    this.caminosPared = [];
    for (const [nombre, [eje, valor]] of Object.entries(this.paredes)) {
      const i = eje === "x" ? 0 : 1, img = [...this.T];
      img[i] = 2 * valor - img[i];
      const d = Math.hypot(this.R[0] - img[0], this.R[1] - img[1]);
      const u = (valor - img[i]) / (this.R[i] - img[i]);
      const pr = [img[0] + u * (this.R[0] - img[0]), img[1] + u * (this.R[1] - img[1])];
      this.caminosPared.push({ nombre: `pared ${nombre}`, d, a: this.gammaPared / d, puntos: [this.T, pr, this.R] });
    }
    // Parte fija de H (paredes) y fase del directo, por subportadora
    this.HparRe = []; this.HparIm = []; this.fdRe = []; this.fdIm = [];
    for (const f of this.freqs) {
      let re = 0, im = 0;
      for (const c of this.caminosPared) { const ph = -2 * Math.PI * c.d * f / C_LUZ; re += c.a * Math.cos(ph); im += c.a * Math.sin(ph); }
      this.HparRe.push(re); this.HparIm.push(im);
      const ph = -2 * Math.PI * this.dDirecto * f / C_LUZ;
      this.fdRe.push(Math.cos(ph)); this.fdIm.push(Math.sin(ph));
    }
  }

  factorBloqueo(p) {
    const d = distanciaASegmento(p, this.T, this.R);
    const w = Math.min(1, Math.max(0, (this.radio + 0.10 - d) / 0.10));
    return 1 - w * Math.min(Math.abs(this.contraste), 1) * (1 - this.transmision);
  }

  dCuerpo(p, z = null) {
    let d1 = Math.hypot(p[0] - this.T[0], p[1] - this.T[1]), d2 = Math.hypot(this.R[0] - p[0], this.R[1] - p[1]);
    if (z !== null && finito(z) && this.alturaAntenas !== null) { const dz = z - this.alturaAntenas; d1 = Math.hypot(d1, dz); d2 = Math.hypot(d2, dz); }
    return d1 + d2;
  }

  // |H_k| (y re/im) para una posición p = [x, y] (o null = habitación vacía)
  H(p, z = null) {
    const n = this.freqs.length, re = new Float64Array(n), im = new Float64Array(n);
    const pres = p !== null;
    const a0 = (pres ? this.factorBloqueo(p) : 1) / this.dDirecto;
    const db = pres ? this.dCuerpo(p, z) : 0, ab = pres ? this.gammaCuerpo / db : 0;
    for (let k = 0; k < n; k++) {
      re[k] = a0 * this.fdRe[k] + this.HparRe[k];
      im[k] = a0 * this.fdIm[k] + this.HparIm[k];
      if (pres) { const ph = -2 * Math.PI * db * this.freqs[k] / C_LUZ; re[k] += ab * Math.cos(ph); im[k] += ab * Math.sin(ph); }
    }
    return { re, im };
  }

  caminos(p = null, z = null) {
    const bloqueo = p ? this.factorBloqueo(p) : 1;
    const out = [{ nombre: "directo", puntos: [this.T, this.R], d: this.dDirecto, amplitud: bloqueo / this.dDirecto, bloqueado: bloqueo < 0.999 }];
    for (const c of this.caminosPared) out.push({ nombre: c.nombre, puntos: c.puntos, d: c.d, amplitud: Math.abs(c.a), bloqueado: false });
    if (p) { const d = this.dCuerpo(p, z); out.push({ nombre: "cuerpo", puntos: [this.T, p, this.R], d, amplitud: Math.abs(this.gammaCuerpo) / d, bloqueado: false }); }
    return out;
  }
}

// ---------------------------------------------------------------- métricas
export function sigmaPorSubportadora(A) {           // A: array de filas (muestras) × K
  const N = A.length, K = A.length ? A[0].length : 0, out = new Float64Array(K);
  if (N < 2) return out;
  for (let k = 0; k < K; k++) {
    let m = 0; for (let i = 0; i < N; i++) m += A[i][k]; m /= N;
    let v = 0; for (let i = 0; i < N; i++) v += (A[i][k] - m) ** 2;
    out[k] = Math.sqrt(v / N);
  }
  return out;
}
export const calcularV = (A, escala = 1) => { const s = sigmaPorSubportadora(A); return s.length ? s.reduce((a, b) => a + b, 0) / s.length * escala : 0; };

function dft(x) {                                     // |X|² con FFT radix-2 (o DFT directa si n no es potencia de 2)
  const n = x.length;
  if ((n & (n - 1)) !== 0) {
    const out = new Float64Array(n);
    for (let k = 0; k < n; k++) { let re = 0, im = 0; for (let t = 0; t < n; t++) { const a = -2 * Math.PI * k * t / n; re += x[t] * Math.cos(a); im += x[t] * Math.sin(a); } out[k] = re * re + im * im; }
    return out;
  }
  const re = Float64Array.from(x), im = new Float64Array(n);
  for (let i = 1, j = 0; i < n; i++) { let bit = n >> 1; for (; j & bit; bit >>= 1) j ^= bit; j ^= bit; if (i < j) { [re[i], re[j]] = [re[j], re[i]]; } }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = -2 * Math.PI / len;
    for (let i = 0; i < n; i += len) for (let j = 0; j < len / 2; j++) {
      const wr = Math.cos(ang * j), wi = Math.sin(ang * j);
      const ur = re[i + j], ui = im[i + j], vr = re[i + j + len / 2] * wr - im[i + j + len / 2] * wi, vi = re[i + j + len / 2] * wi + im[i + j + len / 2] * wr;
      re[i + j] = ur + vr; im[i + j] = ui + vi; re[i + j + len / 2] = ur - vr; im[i + j + len / 2] = ui - vi;
    }
  }
  const out = new Float64Array(n); for (let k = 0; k < n; k++) out[k] = re[k] * re[k] + im[k] * im[k];
  return out;
}

// Welch (ventana de Hann periódica, 50 % de solape, media quitada por segmento, densidad) promediado sobre subportadoras.
export function espectro(A, fs, nperseg = 128) {
  const N = A.length, K = N ? A[0].length : 0, n = Math.min(nperseg, N);
  if (n < 8) return { f: [], P: [] };
  const paso = n - Math.floor(n / 2), nseg = Math.floor((N - n) / paso) + 1;
  const win = Array.from({ length: n }, (_, i) => 0.5 - 0.5 * Math.cos(2 * Math.PI * i / n));
  const escala = 1 / (fs * win.reduce((s, w) => s + w * w, 0));
  const nf = Math.floor(n / 2) + 1, P = new Float64Array(nf);
  for (let k = 0; k < K; k++) for (let s = 0; s < nseg; s++) {
    const seg = new Float64Array(n); let m = 0;
    for (let i = 0; i < n; i++) { seg[i] = A[s * paso + i][k]; m += seg[i]; }
    m /= n; for (let i = 0; i < n; i++) seg[i] = (seg[i] - m) * win[i];
    const X = dft(seg);
    for (let i = 0; i < nf; i++) { let v = X[i] * escala; if (i > 0 && !(n % 2 === 0 && i === nf - 1)) v *= 2; P[i] += v / (nseg * K); }
  }
  return { f: Array.from({ length: nf }, (_, i) => i * fs / n), P: Array.from(P) };
}
export function energiaBanda(f, P, banda = [0.5, 20]) {
  const idx = f.map((x, i) => i).filter((i) => f[i] >= banda[0] && f[i] <= banda[1]);
  if (idx.length < 2) return 0;
  let e = 0; for (let j = 1; j < idx.length; j++) e += (P[idx[j]] + P[idx[j - 1]]) / 2 * (f[idx[j]] - f[idx[j - 1]]);
  return e;
}
export function pico(f, P, banda = [0.5, 20]) {
  let mejor = NaN, pm = -Infinity;
  f.forEach((x, i) => { if (x >= banda[0] && x <= banda[1] && P[i] > pm) { pm = P[i]; mejor = x; } });
  return mejor;
}
export const frecuenciaEsperada = (v, lam) => 2 * Math.abs(v) / lam;
export const giroDeFase = (dx, lam) => 4 * Math.PI * Math.abs(dx) / lam;

// ---------------------------------------------------------------- simulador a 100 muestras/s
export class SimuladorWifi {
  constructor(w) {
    this.cfg = w; this.canal = new CanalWifi(w); this.fs = w.muestras_por_s; this.ruido = w.ruido_sigma;
    this.escalaV = (w.escala_V === "auto" || w.escala_V === null || w.escala_V === undefined) ? 5 / Math.max(this.ruido, 1e-9) : Number(w.escala_V);
    this.umbralV = w.umbral_V; this.ventanaSigma = w.ventana_sigma_s; this.ventanaWelch = w.ventana_welch_s;
    this.bandaEnergia = w.banda_energia_hz; this.historialS = w.historial_s;
    this.nMax = Math.floor(this.fs * Math.max(this.historialS, this.ventanaWelch + 2));
    this.tBuf = []; this.ABuf = []; this.pos = []; this.Vhist = []; this.tGen = null; this.ultimo = null;
  }
  fijarBanda(b) { this.canal.fijarBanda(b); }
  fijarContraste(c) { this.canal.contraste = Math.min(1, Math.max(0, c)); }
  calibrarEscala(objetivo = 5, segundos = 3) {
    if (this.tBuf.length < 10) return this.escalaV;
    const tFin = this.tBuf[this.tBuf.length - 1];
    const A = this.ABuf.filter((_, i) => this.tBuf[i] >= tFin - segundos);
    const crudo = calcularV(A, 1); if (crudo > 0) this.escalaV = objetivo / crudo;
    return this.escalaV;
  }
  alimentar(t, p = null, z = null) {
    const presente = p !== null && p.every(finito);
    const zz = finito(z) ? z : NaN;
    this.pos.push([t, presente ? p[0] : NaN, presente ? p[1] : NaN, presente]);
    while (this.pos.length && this.pos[0][0] < t - 3) this.pos.shift();
    if (this.ultimo === null) { this.ultimo = [t, p, presente, zz]; this.tGen = t; return; }
    const [t0, p0, pres0, z0] = this.ultimo;
    const n = Math.floor((t - this.tGen) * this.fs + 1e-9);
    for (let i = 1; i <= n; i++) {
      const ts = this.tGen + i / this.fs, u = Math.min(1, Math.max(0, (ts - t0) / Math.max(t - t0, 1e-9)));
      let P = null, zi = null;
      if (presente && pres0) P = [p0[0] + u * (p[0] - p0[0]), p0[1] + u * (p[1] - p0[1])];
      else if (presente || pres0) P = u < 0.5 ? (pres0 ? p0 : null) : (presente ? p : null);
      if (this.canal.alturaAntenas !== null && finito(zz)) { const zb = finito(z0) ? z0 : zz; zi = zb + u * (zz - zb); }
      const H = this.canal.H(P, zi), A = new Float64Array(H.re.length);
      for (let k = 0; k < A.length; k++) A[k] = Math.hypot(H.re[k] + this.ruido * randn(), H.im[k] + this.ruido * randn());
      this.tBuf.push(ts); this.ABuf.push(A);
    }
    if (n > 0) this.tGen += n / this.fs;
    if (this.tBuf.length > this.nMax) { const q = this.tBuf.length - this.nMax; this.tBuf.splice(0, q); this.ABuf.splice(0, q); }
    this.ultimo = [t, p, presente, zz];
  }
  _ventana(seg) {
    if (!this.tBuf.length) return { t: [], A: [] };
    const tFin = this.tBuf[this.tBuf.length - 1]; let k = 0;
    while (k < this.tBuf.length && this.tBuf[k] < tFin - seg) k++;
    return { t: this.tBuf.slice(k), A: this.ABuf.slice(k) };
  }
  _velocidad() {
    const pts = this.pos.filter((q) => q[3]);
    if (pts.length < 3) return [NaN, NaN];
    const tf = pts[pts.length - 1][0], sel = pts.filter((q) => q[0] >= tf - 0.5);
    if (sel.length < 2 || tf - sel[0][0] < 0.05) return [NaN, NaN];
    const tt = sel.map((q) => q[0]);
    const vx = polyfit(tt, sel.map((q) => q[1]), 1)[0], vy = polyfit(tt, sel.map((q) => q[2]), 1)[0];
    const db = polyfit(tt, sel.map((q) => this.canal.dCuerpo([q[1], q[2]])), 1)[0];
    return [Math.hypot(vx, vy), db];
  }
  _desplazamiento1s() {
    const pts = this.pos.filter((q) => q[3]);
    if (pts.length < 2) return NaN;
    const tf = pts[pts.length - 1][0];
    let ini = pts[0]; for (const q of pts) if (Math.abs(q[0] - (tf - 1)) < Math.abs(ini[0] - (tf - 1))) ini = q;
    if (tf - ini[0] < 0.5) return NaN;
    return Math.hypot(pts[pts.length - 1][1] - ini[1], pts[pts.length - 1][2] - ini[2]);
  }
  metricas() {
    const lam = this.canal.lam, r = (x, d = 2) => finito(x) ? Math.round(x * 10 ** d) / 10 ** d : null;
    const { t, A } = this._ventana(this.ventanaSigma);
    const V = A.length >= 10 ? calcularV(A, this.escalaV) : 0;
    const tNow = t.length ? t[t.length - 1] : 0;
    this.Vhist.push([tNow, V]);
    while (this.Vhist.length && this.Vhist[0][0] < tNow - this.historialS) this.Vhist.shift();
    const w = this._ventana(this.ventanaWelch);
    const { f, P } = w.A.length >= 32 ? espectro(w.A, this.fs, Math.min(128, w.A.length)) : { f: [], P: [] };
    const [v, ddb] = this._velocidad(), dx = this._desplazamiento1s();
    const u = this.ultimo, p = u && u[2] ? u[1] : null, z = u && u[2] && this.canal.alturaAntenas !== null ? u[3] : null;
    const pk = pico(f, P, this.bandaEnergia);
    const sig = A.length >= 2 ? Array.from(sigmaPorSubportadora(A), (s) => s * this.escalaV) : new Array(this.canal.nSub).fill(0);
    return {
      etiqueta: "CALCULADO", t: tNow, V: r(V), umbral_V: this.umbralV, movimiento: V > this.umbralV, sigma_k: sig,
      espectro_f: f.filter((x) => x <= 50), espectro_P: P.filter((_, i) => f[i] <= 50),
      pico_hz: r(pk), energia_banda: energiaBanda(f, P, this.bandaEnergia), banda_energia_hz: this.bandaEnergia,
      banda_ghz: this.canal.banda, f_central_ghz: r(this.canal.fCentral / 1e9, 4), lambda_m: r(lam, 4),
      velocidad_ms: r(v, 3), f_esperada_hz: finito(v) ? r(frecuenciaEsperada(v, lam)) : null,
      f_geometrica_hz: finito(ddb) ? r(Math.abs(ddb) / lam) : null, desplazamiento_1s_m: r(dx, 3),
      delta_fase_rad: finito(dx) ? r(giroDeFase(dx, lam)) : null, gamma_cuerpo: r(Math.abs(this.canal.gammaCuerpo), 3),
      contraste: r(this.canal.contraste), posicion_m: p ? [r(p[0], 3), r(p[1], 3)] : null, caminos: this.canal.caminos(p, z),
      modelo: this.canal.alturaAntenas !== null ? "3D" : "2D (planta)", escala_V: r(this.escalaV),
    };
  }
  historialV() { return this.Vhist.map(([t, v]) => [Math.round(t * 100) / 100, Math.round(v * 100) / 100]); }
}
