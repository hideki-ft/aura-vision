// Marioneta: persona sintética controlada con el teclado (o botones táctiles).
// Genera los 17 puntos clave como si vinieran de la cámara, con proporciones humanas (tablas de Winter)
// y física simple: la caída es caída libre de la cadera (h = h0 − g·t²/2) y el salto es balístico.
// Se usa en la versión web y en la app de escritorio (modo --sintetico).

const G = 9.81;
const rad = (g) => (g * Math.PI) / 180;
const lerp = (a, b, u) => a + (b - a) * u;
const suave = (u) => 0.5 - 0.5 * Math.cos(Math.PI * Math.min(1, Math.max(0, u)));
const rnd = () => { let u = 0, v = 0; while (!u) u = Math.random(); while (!v) v = Math.random(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };

// Acciones del menú: tecla, texto, qué debería detectar AURA.
export const ACCIONES = [
  { id: "izquierda", teclas: ["ArrowLeft"], etiqueta: "←", nombre: "Caminar a la izquierda", detecta: "caminando", mantener: true },
  { id: "derecha", teclas: ["ArrowRight"], etiqueta: "→", nombre: "Caminar a la derecha", detecta: "caminando", mantener: true },
  { id: "correr", teclas: ["Shift"], etiqueta: "Shift", nombre: "Correr (con ← →)", detecta: "caminando", mantener: true },
  { id: "saltar", teclas: ["ArrowUp", " "], etiqueta: "↑ / Espacio", nombre: "Saltar", detecta: "saltando" },
  { id: "agacharse", teclas: ["ArrowDown"], etiqueta: "↓", nombre: "Agacharse (mantener)", detecta: "sentado / incierto", mantener: true },
  { id: "sentarse", teclas: ["s", "S"], etiqueta: "S", nombre: "Sentarse / levantarse de la silla", detecta: "sentado" },
  { id: "caer", teclas: ["c", "C"], etiqueta: "C", nombre: "Caerse (sobre el colchón)", detecta: "POSIBLE CAÍDA" },
  { id: "acostarse", teclas: ["a", "A"], etiqueta: "A", nombre: "Acostarse despacio", detecta: "en el suelo (no es caída)" },
  { id: "levantarse", teclas: ["l", "L"], etiqueta: "L", nombre: "Levantarse del suelo", detecta: "de pie" },
  { id: "sentadillas", teclas: ["e", "E"], etiqueta: "E", nombre: "Ejercicio: sentadillas", detecta: "de pie ↔ sentado" },
  { id: "tijeras", teclas: ["j", "J"], etiqueta: "J", nombre: "Ejercicio: saltos de tijera", detecta: "saltando" },
  { id: "rutina", teclas: ["r", "R"], etiqueta: "R", nombre: "Rutina automática", detecta: "todo" },
];

const RUTINA = [["derecha", 2.2], ["quieto", 1.2], ["saltar", 1.6], ["quieto", 1.0], ["sentarse", 4.0], ["sentarse", 2.0],
  ["sentadillas", 5.0], ["sentadillas", 1.5], ["izquierda", 2.0], ["quieto", 1.0], ["caer", 7.0], ["levantarse", 4.0],
  ["tijeras", 4.0], ["tijeras", 1.5], ["acostarse", 6.0], ["levantarse", 4.0]];

export class Marioneta {
  constructor({ estatura = 1.70, ppm = 250, suelo = 650, ancho = 1280, alto = 720, ruido = 0.8 } = {}) {
    Object.assign(this, { S: estatura, ppm, sueloPx: suelo, ancho, alto, ruido });
    const S = estatura;
    this.L = { muslo: 0.245 * S, pierna: 0.246 * S, tronco: 0.288 * S, brazo: 0.186 * S, antebrazo: 0.146 * S, tobillo: 0.039 * S };
    this.x = 2.0; this.dir = 1;                  // posición (m) y hacia dónde mira (+1 derecha, −1 izquierda)
    this.p = this._pie();                        // parámetros actuales de la postura
    this.modo = "de_pie";                        // de_pie | caminando | agachado | sentado | suelo | clip
    this.clip = null; this.fase = 0; this.amp = 0; this.t = 0;
    this.teclas = new Set(); this.ejercicio = null; this.tEj = 0;
    this.silla = null; this.rutina = null;
    this.colchon = [3.0, 4.75];                  // zona del colchón (m)
    this.texto = "De pie";
  }

  // ---------------------------------------------------------------- posturas (ángulos en grados)
  _pie() { return { torso: 2, m: [0, 0], p: [0, 0], b: [4, -4], dy: 0, hh: null }; }
  _agachado() { return { torso: 32, m: [72, 72], p: [-38, -38], b: [55, 50], dy: 0, hh: null }; }
  _sentado() { return { torso: 6, m: [88, 88], p: [0, 0], b: [25, 20], dy: 0, hh: null }; }
  _tumbado(a, hh) {                               // piernas rectas que giran con el tobillo en el suelo
    const c = Math.min(1, Math.max(0, (hh - this.L.tobillo) / (this.L.muslo + this.L.pierna)));
    const th = (Math.acos(c) * 180) / Math.PI;
    return { torso: -88 * a, m: [th, th], p: [th, th], b: [110 * a, 90 * a], dy: 0, hh };
  }
  _hPiernas(m, p) {
    const pr = [0, 1].map((j) => this.L.muslo * Math.cos(rad(m[j])) + this.L.pierna * Math.cos(rad(p[j])));
    return this.L.tobillo + Math.max(...pr);
  }
  _hh(q) { return q.hh !== null && q.hh !== undefined ? q.hh : this._hPiernas(q.m, q.p); }
  _mezclar(a, b, u) {
    return { torso: lerp(a.torso, b.torso, u), m: [0, 1].map((j) => lerp(a.m[j], b.m[j], u)), p: [0, 1].map((j) => lerp(a.p[j], b.p[j], u)),
      b: [0, 1].map((j) => lerp(a.b[j], b.b[j], u)), dy: lerp(a.dy, b.dy, u),
      hh: a.hh === null && b.hh === null ? null : lerp(this._hh(a), this._hh(b), u) };
  }

  // ---------------------------------------------------------------- entrada (teclado / botones)
  presionar(id) {
    if (id !== "rutina" && this.rutina) { this.rutina = null; this.teclas.clear(); }
    const acc = ACCIONES.find((a) => a.id === id);
    if (acc && acc.mantener) { this.teclas.add(id); return; }
    this._accion(id);
  }
  soltar(id) { this.teclas.delete(id); }
  teclaAAccion(key) { const a = ACCIONES.find((x) => x.teclas.includes(key)); return a ? a.id : null; }

  _accion(id) {
    const enSuelo = this.modo === "suelo" || (this.clip && this.clip.fin === "suelo");
    if (this.clip && !["levantarse"].includes(id)) return;          // terminar el movimiento en curso
    if (id === "rutina") { this.rutina = this.rutina ? null : { i: -1, t: 0 }; this.ejercicio = null; return; }
    if (id === "sentadillas" || id === "tijeras") {
      if (enSuelo || this.modo === "sentado") return;
      this.ejercicio = this.ejercicio === id ? null : id; this.tEj = 0; return;
    }
    this.ejercicio = null;
    if (id === "saltar" && !enSuelo && this.modo !== "sentado") this._clipSalto(0.45);
    else if (id === "caer" && !enSuelo) this._clipCaida();
    else if (id === "acostarse" && !enSuelo) this._clipAcostarse();
    else if (id === "levantarse" && enSuelo && !this.clip) this._clipLevantarse();
    else if (id === "sentarse") {
      if (this.modo === "sentado") this._clipSilla(true);
      else if (!enSuelo) this._clipSilla(false);
    }
  }

  // ---------------------------------------------------------------- movimientos con duración (clips)
  _clipSalto(T) {
    const ini = { ...this.p }, ag = { torso: 25, m: [40, 40], p: [-30, -30], b: [-30, -30], dy: 0, hh: null };
    const v0 = (G * T) / 2, aire = { torso: 2, m: [5, 5], p: [0, 0], b: [150, 150], dy: 0, hh: null };
    this.clip = { dur: 0.35 + 0.15 + T + 0.3, fin: "de_pie", texto: "Saltando", f: (t) => {
      if (t < 0.35) return this._mezclar(ini, ag, suave(t / 0.35));
      if (t < 0.5) return this._mezclar(ag, { ...this._pie(), b: [120, 120] }, suave((t - 0.35) / 0.15));
      if (t < 0.5 + T) { const u = t - 0.5; return { ...aire, dy: Math.max(0, v0 * u - 0.5 * G * u * u) }; }
      return this._mezclar(this._mezclar(this._pie(), ag, 0.6), this._pie(), suave((t - 0.5 - T) / 0.3));
    } };
  }
  _clipCaida() {
    const ini = { ...this.p }, h0 = this._hh(ini), h1 = 0.06 * this.S, T = Math.sqrt((2 * (h0 - h1)) / G);
    const dePie = Math.abs(ini.m[0]) < 20 && Math.abs(ini.p[0]) < 20;
    this.clip = { dur: T + 0.05, fin: "suelo", texto: "¡Cayendo!", f: (t) => {
      const hh = Math.max(h1, h0 - 0.5 * G * Math.min(t, T) ** 2), a = (h0 - hh) / (h0 - h1);
      const fin = this._tumbado(a, hh);
      return dePie ? fin : { ...this._mezclar(ini, this._tumbado(1, h1), a), hh };
    } };
  }
  _clipAcostarse() {
    const ini = { ...this.p }, h0 = this._hh(ini), h1 = 0.06 * this.S;
    this.clip = { dur: 3.0, fin: "suelo", texto: "Acostándose despacio", f: (t) => {
      const a = suave(t / 3.0), hh = h0 - (h0 - h1) * a;
      return Math.abs(ini.m[0]) < 20 ? this._tumbado(a, hh) : { ...this._mezclar(ini, this._tumbado(1, h1), a), hh };
    } };
  }
  _clipLevantarse() {
    const h0 = 0.06 * this.S, h1 = this._hPiernas([0, 0], [0, 0]);
    this.clip = { dur: 2.6, fin: "de_pie", texto: "Levantándose", f: (t) => {
      const a = 1 - suave(t / 2.6);
      if (a > 0.45) return this._tumbado(a, h0 + (h1 - h0) * (1 - a));
      return this._mezclar(this._agachado(), this._pie(), suave((0.45 - a) / 0.45));   // se incorpora por cuclillas
    } };
  }
  _clipSilla(levantarse) {
    const ini = { ...this.p };
    if (!levantarse) this.silla = this.x - 0.16 * this.dir;
    this.clip = { dur: 1.2, fin: levantarse ? "de_pie" : "sentado", texto: levantarse ? "Levantándose de la silla" : "Sentándose",
      f: (t) => {
        const u = suave(t / 1.2), obj = levantarse ? this._pie() : this._sentado();
        const q = this._mezclar(ini, obj, u); q.torso += 25 * Math.sin(Math.PI * u); return q;
      } };
  }

  // ---------------------------------------------------------------- simulación
  actualizar(dt) {
    dt = Math.min(Math.max(dt, 0), 0.1);
    this.t += dt;
    this._rutina(dt);
    if (this.clip) {
      this.clip.t = (this.clip.t || 0) + dt;
      this.p = this.clip.f(this.clip.t);
      this.texto = this.clip.texto;
      if (this.clip.t >= this.clip.dur) {
        this.modo = this.clip.fin; this.clip = null;
      }
    } else if (this.modo === "suelo") {
      this.p = this._tumbado(1, 0.06 * this.S + 0.002 * this.S * Math.sin(2 * Math.PI * 0.25 * this.t));
      this.p.m = [88, 88]; this.p.p = [85, 85]; this.texto = "En el suelo (L para levantarse)";
    } else if (this.modo === "sentado") {
      this.p = this._sentado(); this.texto = "Sentado (S para levantarse)";
    } else this._dePie(dt);
    return this.puntos();
  }

  _dePie(dt) {
    const izq = this.teclas.has("izquierda"), der = this.teclas.has("derecha"), corre = this.teclas.has("correr");
    const andar = izq !== der;
    if (andar) this.dir = der ? 1 : -1;
    const v = corre ? 2.6 : 1.1, f = corre ? 1.45 : 0.9;
    this.amp += ((andar ? 1 : 0) - this.amp) * (1 - Math.exp(-dt / 0.18));
    this.fase += 2 * Math.PI * f * dt * (andar ? 1 : this.amp);
    if (andar || this.amp > 0.02) this.x += this.dir * v * this.amp * dt;
    this.x = Math.min(this.ancho / this.ppm - 1.0, Math.max(1.0, this.x));   // margen: siempre se ve entera, también tumbada
    let obj;
    if (this.teclas.has("agacharse") && !andar) { obj = this._agachado(); this.texto = "Agachado"; }
    else if (this.ejercicio === "sentadillas") {
      this.tEj += dt; obj = this._mezclar(this._pie(), this._agachado(), 0.5 - 0.5 * Math.cos(2 * Math.PI * 0.45 * this.tEj));
      this.texto = "Sentadillas";
    } else if (this.ejercicio === "tijeras") {
      this.tEj += dt;
      const per = 0.75, u = this.tEj % per, Tv = 0.32, v0 = (G * Tv) / 2, arr = Math.floor(this.tEj / per) % 2;
      const dy = u < Tv ? v0 * u - 0.5 * G * u * u : 0;
      const brazo = arr ? lerp(20, 170, suave(u / per)) : lerp(170, 20, suave(u / per));
      this.p = { torso: 2, m: [8, -8], p: [4, -4], b: [brazo, brazo], dy: Math.max(0, dy), hh: null };
      this.texto = "Saltos de tijera"; return;
    } else {
      const A = 25 * this.amp * (corre ? 1.4 : 1), fl = (corre ? 60 : 35) * this.amp, fs = this.fase;
      obj = { torso: 2 + 0.4 * Math.sin(0.6 * this.t) + (corre ? 10 : 4) * this.amp, m: [A * Math.sin(fs), -A * Math.sin(fs)],
        p: [A * Math.sin(fs) - fl * Math.max(0, -Math.cos(fs)), -A * Math.sin(fs) - fl * Math.max(0, Math.cos(fs))],
        b: [-22 * this.amp * Math.sin(fs) + 4, 22 * this.amp * Math.sin(fs) - 4], dy: 0, hh: null };
      this.texto = andar ? (corre ? "Corriendo" : "Caminando") : "De pie";
      if (this.amp > 0.05) { this.p = obj; return; }                 // al caminar, la postura sigue al ciclo de marcha
    }
    this.p = this._mezclar(this.p, obj, 1 - Math.exp(-dt / 0.15));
  }

  _rutina(dt) {
    const r = this.rutina; if (!r) return;
    r.t -= dt;
    if (r.t > 0 || this.clip) return;
    this.teclas.clear();
    r.i = (r.i + 1) % RUTINA.length;
    const [acc, dur] = RUTINA[r.i]; r.t = dur;
    if (acc === "izquierda" || acc === "derecha") this.teclas.add(acc);
    else if (acc !== "quieto") { const rr = this.rutina; this.rutina = null; this._accion(acc); this.rutina = rr; }
  }

  // ---------------------------------------------------------------- 17 puntos clave (como YOLO/RTMPose)
  _cuerpo() {                                     // puntos en metros (x, altura) mirando hacia +x
    const S = this.S, q = this.p, hh = this._hh(q), L = this.L;
    const k = Array.from({ length: 17 }, () => [0, 0]);
    const hip = [0, hh + q.dy], f = rad(q.torso), u = [Math.sin(f), Math.cos(f)], ad = [Math.cos(f), -Math.sin(f)];
    const sh = [hip[0] + L.tronco * u[0], hip[1] + L.tronco * u[1]], cab = [sh[0] + 0.1 * S * u[0], sh[1] + 0.1 * S * u[1]];
    const off = 0.006 * S;
    [[0, 11, 13, 15, 5, 7, 9, 1, 3, -1], [1, 12, 14, 16, 6, 8, 10, 2, 4, 1]].forEach(([j, ic, ir, it, ih, io, im, iy, ie, s]) => {
      const am = rad(q.m[j]), ap = rad(q.p[j]), b = rad(q.b[j]);
      const cad = [hip[0] + s * off, hip[1]], rod = [cad[0] + L.muslo * Math.sin(am), cad[1] - L.muslo * Math.cos(am)];
      const tob = [rod[0] + L.pierna * Math.sin(ap), rod[1] - L.pierna * Math.cos(ap)];
      const hom = [sh[0] + s * off, sh[1]], codo = [hom[0] + L.brazo * Math.sin(b), hom[1] - L.brazo * Math.cos(b)];
      const mun = [codo[0] + L.antebrazo * Math.sin(b + 0.2), codo[1] - L.antebrazo * Math.cos(b + 0.2)];
      k[ic] = cad; k[ir] = rod; k[it] = tob; k[ih] = hom; k[io] = codo; k[im] = mun;
      k[iy] = [cab[0] + 0.03 * S * ad[0] + 0.012 * S * u[0], cab[1] + 0.03 * S * ad[1] + 0.012 * S * u[1]];
      k[ie] = [cab[0] - 0.01 * S * ad[0] + s * off, cab[1] - 0.01 * S * ad[1]];
    });
    k[0] = [cab[0] + 0.045 * S * ad[0], cab[1] + 0.045 * S * ad[1]];
    return { k, cab, hip };
  }

  aPx([x, h]) { return [(this.x + this.dir * x) * this.ppm, this.sueloPx - h * this.ppm]; }

  // Devuelve { kps (17 × [x, y] px), scores (17), caja [x1, y1, x2, y2] } con un poco de ruido, como una cámara.
  puntos() {
    const { k, cab } = this._cuerpo(), S = this.S;
    const kps = k.map((q) => { const [x, y] = this.aPx(q); return [x + this.ruido * rnd(), y + this.ruido * rnd()]; });
    const scores = k.map(() => Math.min(1, Math.max(0, 0.9 + 0.03 * rnd())));
    const tope = this.aPx([0, Math.max(cab[1] + 0.07 * S, ...k.map((q) => q[1]))])[1];
    const xs = kps.map((q) => q[0]), ys = kps.map((q) => q[1]);
    const caja = [Math.min(...xs) - 0.06 * S * this.ppm, Math.min(tope, ...ys), Math.max(...xs) + 0.06 * S * this.ppm, Math.max(...ys) + 0.03 * S * this.ppm];
    return { kps, scores, caja };
  }

  // ---------------------------------------------------------------- dibujo "bonito" (habitación + persona con volumen)
  dibujar(ctx) {
    const W = this.ancho, H = this.alto, P = this.ppm, yS = this.sueloPx;
    const fondo = ctx.createLinearGradient(0, 0, 0, yS);
    fondo.addColorStop(0, "#2c3e57"); fondo.addColorStop(1, "#3d5573");
    ctx.fillStyle = fondo; ctx.fillRect(0, 0, W, yS);
    ctx.fillStyle = "#4a6382"; ctx.fillRect(80, 90, 260, 170); ctx.fillStyle = "#9cc7e8"; ctx.fillRect(92, 102, 236, 146);   // ventana
    ctx.strokeStyle = "#4a6382"; ctx.lineWidth = 8; ctx.beginPath(); ctx.moveTo(210, 102); ctx.lineTo(210, 248); ctx.moveTo(92, 175); ctx.lineTo(328, 175); ctx.stroke();
    ctx.fillStyle = "#1f2d40"; ctx.fillRect(0, yS - 18, W, 18);                                                    // zócalo
    const piso = ctx.createLinearGradient(0, yS, 0, H); piso.addColorStop(0, "#8a6a4a"); piso.addColorStop(1, "#5e4630");
    ctx.fillStyle = piso; ctx.fillRect(0, yS, W, H - yS);
    ctx.strokeStyle = "rgba(0,0,0,.18)"; ctx.lineWidth = 2;
    for (let x = -200; x < W + 200; x += 90) { ctx.beginPath(); ctx.moveTo(x, yS); ctx.lineTo(x + (x - W / 2) * 0.6, H); ctx.stroke(); }
    const [c0, c1] = this.colchon;                                                                               // colchón
    ctx.fillStyle = "#2f7fb8"; this._redondeado(ctx, c0 * P, yS - 16, (c1 - c0) * P, 30, 10); ctx.fill();
    ctx.fillStyle = "#5aa7dd"; this._redondeado(ctx, c0 * P, yS - 16, (c1 - c0) * P, 10, 6); ctx.fill();
    ctx.fillStyle = "rgba(255,255,255,.85)"; ctx.font = "bold 18px system-ui"; ctx.fillText("colchón", c0 * P + 12, yS + 6);
    if (this.silla !== null) this._silla(ctx);
    const { k, cab, hip } = this._cuerpo();
    const alt = Math.max(0, Math.min(...k.map((q) => q[1])));                                                    // sombra
    ctx.fillStyle = `rgba(0,0,0,${0.35 - Math.min(0.25, alt)})`;
    ctx.beginPath(); ctx.ellipse((this.x + this.dir * hip[0]) * P, yS + 4, (0.22 + 0.5 * Math.min(1, Math.abs(this.p.torso) / 90)) * this.S * P * 0.55, 10, 0, 0, 7); ctx.fill();
    const px = (q) => this.aPx(q), S = this.S;
    const miembro = (a, b, ancho, col) => { const p1 = px(a), p2 = px(b); ctx.strokeStyle = col; ctx.lineWidth = ancho; ctx.lineCap = "round"; ctx.beginPath(); ctx.moveTo(...p1); ctx.lineTo(...p2); ctx.stroke(); };
    const lejos = 0, cerca = 1, piel = "#e9b48a", camisa = ["#1b8f73", "#23b08e"], pant = ["#273a66", "#34508a"], zap = "#222";
    const brazo = (lado, j) => { const [h, c, m] = j === 0 ? [5, 7, 9] : [6, 8, 10]; miembro(k[h], k[c], 0.06 * S * P, camisa[lado]); miembro(k[c], k[m], 0.05 * S * P, piel); };
    const pierna = (lado, j) => { const [c, r, t] = j === 0 ? [11, 13, 15] : [12, 14, 16]; miembro(k[c], k[r], 0.095 * S * P, pant[lado]); miembro(k[r], k[t], 0.075 * S * P, pant[lado]);
      const tp = px(k[t]); ctx.fillStyle = zap; ctx.beginPath(); ctx.ellipse(tp[0] + this.dir * 10, tp[1] + 6, 18, 9, 0, 0, 7); ctx.fill(); };
    brazo(lejos, 0); pierna(lejos, 0);
    const hm = [(k[11][0] + k[12][0]) / 2, (k[11][1] + k[12][1]) / 2], sm = [(k[5][0] + k[6][0]) / 2, (k[5][1] + k[6][1]) / 2];
    miembro(hm, sm, 0.17 * S * P, camisa[cerca]);                                                                 // tronco
    miembro(sm, cab, 0.05 * S * P, piel);                                                                         // cuello
    pierna(cerca, 1); brazo(cerca, 1);
    const cp = px(cab), r = 0.068 * S * P;                                                                        // cabeza
    ctx.fillStyle = piel; ctx.beginPath(); ctx.arc(cp[0], cp[1], r, 0, 7); ctx.fill();
    ctx.fillStyle = "#3b2a20"; ctx.beginPath(); ctx.arc(cp[0] - this.dir * r * 0.15, cp[1] - r * 0.15, r * 0.95, Math.PI * 1.05, Math.PI * 1.95); ctx.fill();
    const ojo = px(k[0]); ctx.fillStyle = "#222"; ctx.beginPath(); ctx.arc((ojo[0] + cp[0]) / 2 + this.dir * 4, (ojo[1] + cp[1]) / 2 - 6, 4, 0, 7); ctx.fill();
    ctx.fillStyle = "rgba(0,0,0,.55)"; this._redondeado(ctx, 12, H - 52, 430, 40, 8); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.font = "bold 22px system-ui"; ctx.fillText(`🎮 ${this.texto}${this.rutina ? " · rutina automática" : ""}`, 24, H - 24);
  }
  _silla(ctx) {
    const P = this.ppm, yS = this.sueloPx, x = this.silla * P, h = 0.285 * this.S * P - 0.03 * this.S * P, d = this.dir;
    ctx.strokeStyle = "#6b4a2b"; ctx.lineWidth = 10; ctx.lineCap = "round"; ctx.beginPath();
    ctx.moveTo(x - d * 45, yS); ctx.lineTo(x - d * 45, yS - h); ctx.moveTo(x + d * 35, yS); ctx.lineTo(x + d * 35, yS - h);
    ctx.moveTo(x - d * 55, yS - h); ctx.lineTo(x + d * 45, yS - h); ctx.moveTo(x - d * 50, yS - h); ctx.lineTo(x - d * 58, yS - h - 120); ctx.stroke();
  }
  _redondeado(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
}
