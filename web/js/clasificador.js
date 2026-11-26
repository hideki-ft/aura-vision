// Clasificación en tiempo real con reglas físicas — traducción fiel de aura/vision/clasificador.py
import { finito, mediana, percentil, maxFinito, minFinito, media, clip, polyfit } from "./util.js";
import { FRAC_ALTURA_TOBILLO, anguloEn, anguloTorso, estaturaAparente, mediaPuntos, puntosValidos } from "./esqueleto.js";

const G = 9.81;
const ERGUIDO = new Set(["de_pie", "caminando", "sentado", "saltando"]);

export function rampa(x, a, b) {
  if (x === null || x === undefined || !finito(x)) return 0;
  if (a === b) return x >= a ? 1 : 0;
  return clip((x - a) / (b - a), 0, 1);
}

export function puntajesPosturas(h, torso, rodilla, aspecto, vxAbs, c) {
  const erguido = rampa(h, ...c.erguido_cadera) * rampa(torso, ...c.erguido_torso_deg);
  const [v0, v1] = c.caminar_vel_H_s;
  const rod = finito(rodilla) ? rampa(rodilla, ...c.sentado_rodilla_deg) : 0.5;
  return {
    de_pie: erguido * rampa(vxAbs, v1, v0),
    caminando: erguido * rampa(vxAbs, v0, v1),
    sentado: rampa(h, ...c.sentado_cadera_baja) * rampa(h, ...c.sentado_cadera_alta) *
      rampa(torso, ...c.sentado_torso_deg) * (0.5 + 0.5 * rod),
    en_el_suelo: Math.max(rampa(h, ...c.suelo_cadera),
      rampa(h, ...c.suelo_cadera_tumbado) * Math.max(rampa(torso, ...c.suelo_torso_deg), rampa(aspecto, ...c.suelo_aspecto))),
  };
}

export function motivoIncierto(piernas, h, s1, s2, confKp, c) {
  if (!piernas) return "no se ven las piernas: aléjate para que la cámara vea el cuerpo completo";
  if (confKp < c.conf_kp_incierto) return "puntos del cuerpo poco fiables: mejora la luz o acércate un poco";
  if (!finito(h)) return "no se pudo medir la altura de la cadera";
  if (s1 < c.puntaje_min) return "postura no reconocida por las reglas";
  if (s1 - s2 < c.margen_min) return "dos posturas igual de probables";
  return null;
}

export class ClasificadorEstados {
  constructor(cfgClas, alertas = [], estatura = 1.70, umbralPunto = 0.30) {
    this.c = cfgClas;
    this.alertasCfg = [...alertas].sort((a, b) => a.segundos - b.segundos);
    this.estatura = estatura;
    this.umbralPunto = umbralPunto;
    this.reiniciar();
  }

  reiniciar() {
    this.hist = []; this.bufH = []; this.bufTob = [];
    this.estadoEstatico = null; this.candidato = null; this.tCandidato = 0;
    this.tVisto = null; this.caidaPendiente = null; this.caidaConfirmada = null; this.tUltimaCaida = -1e9;
    this.saltandoHasta = -1e9; this.enAireDesde = null; this.ultimoSalto = null;
    this.sueloDesde = null; this.alertasEmitidas = new Set();
    this.salida = { estado: "ausente", confianza: 1.0, presente: false };
  }

  _ventana(t, seg, clave) { return this.hist.filter((e) => e.t >= t - seg).map((e) => e[clave]); }

  _escala(t, xy, caja) {
    const Hf = estaturaAparente(xy);
    if (finito(Hf)) this.bufH.push([t, Hf]);
    while (this.bufH.length && this.bufH[0][0] < t - 10) this.bufH.shift();
    if (this.bufH.length >= 3) return percentil(this.bufH.map((x) => x[1]), 75);
    if (finito(Hf)) return Hf;
    if (caja) return (caja[3] - caja[1]) * 0.9;
    return NaN;
  }

  _suelo(t, xy, H, torso, cadera, caja) {
    const tob = maxFinito([xy[15][1], xy[16][1]]);
    if (finito(tob) && finito(torso) && torso < 30 && (tob - cadera[1]) > 0.35 * H) this.bufTob.push([t, tob]);
    while (this.bufTob.length && this.bufTob[0][0] < t - 10) this.bufTob.shift();
    let yTob;
    if (this.bufTob.length >= 3) yTob = mediana(this.bufTob.map((x) => x[1]));
    else if (finito(tob)) yTob = tob;
    else if (caja) yTob = caja[3] - FRAC_ALTURA_TOBILLO * H;
    else yTob = NaN;
    return [yTob, yTob + FRAC_ALTURA_TOBILLO * H, tob];
  }

  _cinematica(t) {
    const w = this.c.ventana_cinematica_s;
    const pts = this.hist.filter((e) => e.t >= t - w && finito(e.h_m)).map((e) => [e.t - t, e.h_m, e.x_m]);
    if (pts.length < 2) return [NaN, NaN, NaN];
    const tt = pts.map((p) => p[0]), hh = pts.map((p) => p[1]), xx = pts.map((p) => p[2]);
    if (Math.max(...tt) - Math.min(...tt) < 1e-3) return [NaN, NaN, NaN];
    let vy, ay;
    if (pts.length >= 4) { const [a, b] = polyfit(tt, hh, 2); vy = b; ay = 2 * a; }
    else { vy = polyfit(tt, hh, 1)[0]; ay = NaN; }
    const vx = xx.every(finito) ? polyfit(tt, xx, 1)[0] : NaN;
    return [vy, ay, vx];
  }

  actualizar(t, kps = null, scores = null, caja = null) {
    const c = this.c, eventos = [], alertasNuevas = [];
    if (kps === null) {
      if (this.tVisto === null || t - this.tVisto > c.ausente_tras_s) {
        const est = this._estadoEstatico(t, "ausente");
        const final = this._estadoFinal(t, est);
        this._alertas(t, final, alertasNuevas);
        this.salida = { estado: final, confianza: 1.0, presente: false, eventos, alertas: alertasNuevas,
          alerta_activa: this._alertaActiva(), tiempo_en_suelo: this._tiempoSuelo(t), ultimo_salto: this.ultimoSalto };
      } else {
        this.salida = { ...this.salida, presente: false, eventos: [], alertas: [] };
      }
      return this.salida;
    }
    this.tVisto = t;
    const S = this.estatura;
    const xy = puntosValidos(kps, scores, this.umbralPunto);
    const confKp = scores.reduce((a, b) => a + b, 0) / scores.length;
    const cadera = mediaPuntos(xy, [11, 12]), hombros = mediaPuntos(xy, [5, 6]);
    const torso = cadera.every(finito) && hombros.every(finito) ? anguloTorso(cadera, hombros) : NaN;
    const H = this._escala(t, xy, caja);
    const [yTobSuelo, suelo, tob] = this._suelo(t, xy, H, torso, cadera, caja);
    const hRel = finito(cadera[1]) && finito(H) ? (suelo - cadera[1]) / H : NaN;
    const elev = finito(tob) ? (yTobSuelo - tob) / H : NaN;
    const mPx = finito(H) && H > 0 ? S / H : NaN;
    const rod = mediana([anguloEn(xy[11], xy[13], xy[15]), anguloEn(xy[12], xy[14], xy[16])]);
    const aspecto = caja ? (caja[3] - caja[1]) / Math.max(caja[2] - caja[0], 1) : NaN;
    const piernas = [13, 14, 15, 16].filter((j) => finito(xy[j][0])).length >= 2;

    const e = { t, h_rel: hRel, h_m: hRel * S, x_m: finito(mPx) ? cadera[0] * mPx : NaN, torso, rodilla: rod, aspecto, elev };
    this.hist.push(e);
    while (this.hist.length && this.hist[0].t < t - 12) this.hist.shift();
    const [vy, ay, vx] = this._cinematica(t);
    e.vy_rel = finito(vy) ? vy / S : NaN;
    e.vx_rel = finito(vx) ? vx / S : NaN;

    const w = c.ventana_mediana_s;
    const hMed = mediana(this._ventana(t, w, "h_rel"));
    const torsoMed = mediana(this._ventana(t, w, "torso"));
    const rodMed = mediana(this._ventana(t, w, "rodilla"));
    const aspMed = mediana(this._ventana(t, w, "aspecto"));
    const vxAbs = finito(e.vx_rel) ? Math.abs(e.vx_rel) : NaN;
    const P = puntajesPosturas(hMed, torsoMed, rodMed, aspMed, vxAbs, c);
    const orden = Object.keys(P).sort((a, b) => P[b] - P[a]);
    const s1 = P[orden[0]], s2 = P[orden[1]];
    const fkp = 0.5 + 0.5 * rampa(confKp, c.conf_kp_incierto, c.conf_kp_buena);
    const conf = s1 * Math.sqrt(clip((s1 - s2) / 0.3, 0, 1)) * fkp;
    const motivo = motivoIncierto(piernas, hMed, s1, s2, confKp, c);
    const cruda = motivo ? "incierto" : orden[0];
    Object.assign(e, { cruda, conf, P, fkp });

    const est = this._estadoEstatico(t, this._moda(t));
    e.estatico = est;
    this._detectarCaida(t, hRel, eventos);
    this._detectarSalto(t, hRel, elev, eventos);
    const final = this._estadoFinal(t, est);
    this._alertas(t, final, alertasNuevas);

    let confianza;
    if (final === "caida" && this.caidaConfirmada) confianza = this.caidaConfirmada.confianza;
    else if (final === "saltando") confianza = 0.8 * fkp;
    else if (final === "incierto") confianza = Math.min(conf, 0.5);
    else if (final === cruda) confianza = conf;
    else if (final in P) confianza = 0.7 * P[final] * fkp;
    else confianza = 0.5;
    const puntajes = {}; for (const k in P) puntajes[k] = Math.round(P[k] * 1000) / 1000;
    this.salida = {
      estado: final, confianza: Math.round(confianza * 1000) / 1000, presente: true,
      h_m: e.h_m, h_rel: hRel, vy, ay, vx, torso, rodilla: rod, aspecto, conf_kp: confKp, H_px: H, m_por_px: mPx,
      suelo_y: suelo, piernas_visibles: piernas, puntajes, eventos, alertas: alertasNuevas,
      alerta_activa: this._alertaActiva(), tiempo_en_suelo: this._tiempoSuelo(t), ultimo_salto: this.ultimoSalto,
      motivo_incierto: final === "incierto" ? motivo : null,
    };
    return this.salida;
  }

  _moda(t) {
    const votos = this._ventana(t, this.c.ventana_moda_s, "cruda");
    if (!votos.length) return "incierto";
    const cuenta = {}; for (const v of votos) cuenta[v] = (cuenta[v] || 0) + 1;
    const vals = Object.keys(cuenta).sort();          // como np.unique: orden alfabético
    let mejor = vals[0]; for (const v of vals) if (cuenta[v] > cuenta[mejor]) mejor = v;
    const actual = votos[votos.length - 1];
    return cuenta[actual] === cuenta[mejor] ? actual : mejor;
  }

  _estadoEstatico(t, candidato) {
    if (this.estadoEstatico === null) this.estadoEstatico = candidato;
    else if (candidato === this.estadoEstatico) this.candidato = null;
    else {
      if (candidato !== this.candidato) { this.candidato = candidato; this.tCandidato = t; }
      const min = this.c.duracion_min_s[candidato] ?? 0.4;
      if (t - this.tCandidato >= min) { this.estadoEstatico = candidato; this.candidato = null; }
    }
    return this.estadoEstatico;
  }

  _estadoFinal(t, est) {
    if (this.caidaConfirmada && t - this.caidaConfirmada.t_confirmada < this.c.caida_mostrar_s) return "caida";
    if (t < this.saltandoHasta) return "saltando";
    return est;
  }

  _detectarCaida(t, h, eventos) {
    const c = this.c, hist = this.hist;
    if (this.caidaPendiente === null && hist.length >= 2 && t - this.tUltimaCaida > 3.0) {
      const hPrev = hist[hist.length - 2].h_rel;
      if (finito(hPrev) && finito(h) && hPrev > c.caida_cadera_final && c.caida_cadera_final >= h) {
        let i = hist.length - 1;
        while (i > 0 && hist[i - 1].t >= t - c.caida_dur_max_s - 0.5 && finito(hist[i - 1].vy_rel) && hist[i - 1].vy_rel < -0.25) i--;
        const tIni = hist[Math.max(0, i - 1)].t;
        const hIni = maxFinito(hist.filter((x) => x.t >= tIni - 0.15 && x.t <= t).map((x) => x.h_rel));
        this.caidaPendiente = { t_inicio: tIni, t_fin: t, h_inicio: hIni };
      }
    }
    const p = this.caidaPendiente;
    if (p === null || t - p.t_fin < c.caida_confirmar_s) return;
    this.caidaPendiente = null;
    const tramo = hist.filter((x) => x.t > p.t_fin);
    const frac = tramo.length ? tramo.filter((x) => x.cruda === "en_el_suelo").length / tramo.length : 0;
    const vys = hist.filter((x) => x.t >= p.t_inicio && x.t <= p.t_fin + 0.3 && finito(x.vy_rel)).map((x) => x.vy_rel);
    const pico = vys.length ? -Math.min(...vys) : 0;
    const hFin = minFinito(hist.filter((x) => x.t >= p.t_fin).map((x) => x.h_rel));
    const bajada = p.h_inicio - hFin, dur = p.t_fin - p.t_inicio;
    if (dur <= c.caida_dur_max_s && bajada >= c.caida_bajada_min_H && pico >= c.caida_vel_min_H_s && frac >= c.caida_confirmar_frac) {
      const conf = 0.5 + 0.25 * rampa(pico, c.caida_vel_min_H_s, 2 * c.caida_vel_min_H_s) + 0.25 * rampa(frac, c.caida_confirmar_frac, 1.0);
      const r = (x) => Math.round(x * 1000) / 1000;
      const ev = { tipo: "caida", t_inicio: r(p.t_inicio), t_fin: r(p.t_fin), t_confirmada: r(t), duracion_descenso_s: r(dur),
        bajada_m: r(bajada * this.estatura), vel_pico_ms: r(pico * this.estatura), confianza: r(Math.min(conf, 1)) };
      this.caidaConfirmada = ev; this.tUltimaCaida = t; this.sueloDesde = p.t_fin; this.alertasEmitidas = new Set();
      eventos.push(ev);
    }
  }

  _detectarSalto(t, h, elev, eventos) {
    const c = this.c;
    const base = mediana(this.hist.filter((x) => x.estatico === "de_pie" || x.estatico === "caminando").map((x) => x.h_rel));
    const vys = this.hist.filter((x) => x.t >= t - 0.3 && finito(x.vy_rel)).map((x) => x.vy_rel);
    const enAire = finito(elev) && elev > c.vuelo_delta_H;
    if (finito(base) && finito(h) && h > base + c.salto_delta_H && vys.length && Math.max(...vys) >= c.salto_vel_min_H_s &&
        (enAire || !finito(elev))) {
      if (t >= this.saltandoHasta) eventos.push({ tipo: "salto", t: Math.round(t * 1000) / 1000 });
      this.saltandoHasta = t + c.salto_mantener_s;
    }
    if (enAire && this.enAireDesde === null) this.enAireDesde = t;
    else if (!enAire && this.enAireDesde !== null) {
      let tv = t - this.enAireDesde;
      this.enAireDesde = null;
      if (tv >= 0.1 && tv <= 1.2 && t - this.saltandoHasta < 0.5) {
        const delta = c.vuelo_delta_H * this.estatura;
        tv = Math.sqrt(tv * tv + 8 * delta / G);
        this.ultimoSalto = { t: Math.round(t * 100) / 100, t_vuelo_s: Math.round(tv * 1000) / 1000,
          altura_m: Math.round(G * tv * tv / 8 * 1000) / 1000 };
      }
    }
  }

  _tiempoSuelo(t) { return this.sueloDesde === null ? null : Math.round((t - this.sueloDesde) * 10) / 10; }

  _alertas(t, estado, nuevas) {
    if (this.sueloDesde === null) return;
    if (ERGUIDO.has(estado)) { this.sueloDesde = null; return; }
    const enSuelo = t - this.sueloDesde;
    this.alertasCfg.forEach((a, i) => {
      if (enSuelo >= a.segundos && !this.alertasEmitidas.has(i)) {
        this.alertasEmitidas.add(i);
        nuevas.push({ t: Math.round(t * 100) / 100, nivel: i + 1, mensaje: a.mensaje });
      }
    });
  }

  _alertaActiva() {
    if (this.sueloDesde === null || !this.alertasEmitidas.size) return null;
    return this.alertasCfg[Math.max(...this.alertasEmitidas)].mensaje;
  }
}
export { media };
