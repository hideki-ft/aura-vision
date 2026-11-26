// Seguimiento ligero (versión web): predicción con velocidad constante + asociación por IoU y por cercanía.
// Es una simplificación de ByteTrack (aura/vision/seguimiento.py) suficiente para pocas personas.
export function iou(a, b) {
  const x1 = Math.max(a[0], b[0]), y1 = Math.max(a[1], b[1]), x2 = Math.min(a[2], b[2]), y2 = Math.min(a[3], b[3]);
  const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  const u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter;
  return u > 0 ? inter / u : 0;
}
const centro = (b) => [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];

export class Seguidor {
  constructor(c) { this.iouMin = c.iou_minimo; this.maxPerdido = c.max_perdido_s; this.confirmar = c.cuadros_para_confirmar; this.pistas = []; this.sig = 1; }
  actualizar(cajas, t) {
    for (const p of this.pistas) {                       // predicción (velocidad constante del centro)
      const dt = t - p.t; p.pred = p.caja.map((v, i) => v + p.v[i % 2] * dt); p.detIdx = null;
    }
    const libres = new Set(cajas.map((_, i) => i));
    const pares = [];
    for (const p of this.pistas) cajas.forEach((c, i) => pares.push([iou(p.pred, c), p, i]));
    pares.sort((a, b) => b[0] - a[0]);
    for (const [v, p, i] of pares) if (v >= this.iouMin && p.detIdx === null && libres.has(i)) { this._corregir(p, cajas[i], t, i); libres.delete(i); }
    // cambios bruscos de forma (caída): asociar por cercanía del centro
    const dist = [];
    for (const p of this.pistas.filter((q) => q.detIdx === null && q.confirmada)) for (const i of libres) {
      const a = centro(p.pred), b = centro(cajas[i]), esc = Math.max(p.pred[2] - p.pred[0], p.pred[3] - p.pred[1], 1);
      dist.push([Math.hypot(a[0] - b[0], a[1] - b[1]) / esc, p, i]);
    }
    dist.sort((a, b) => a[0] - b[0]);
    for (const [d, p, i] of dist) if (d < 0.6 && p.detIdx === null && libres.has(i)) { this._corregir(p, cajas[i], t, i); libres.delete(i); }
    for (const i of libres) this.pistas.push({ id: this.sig++, caja: cajas[i], pred: cajas[i], v: [0, 0], t, tVisto: t, aciertos: 1, confirmada: false, detIdx: i });
    this.pistas = this.pistas.filter((p) => {
      if (p.aciertos >= this.confirmar) p.confirmada = true;
      const lim = p.confirmada ? this.maxPerdido : 0.5;
      return !(p.detIdx === null && t - p.tVisto > lim);
    });
    return this.pistas.filter((p) => p.confirmada && p.detIdx !== null);
  }
  _corregir(p, caja, t, i) {
    const dt = Math.max(t - p.t, 1e-3), a = centro(p.caja), b = centro(caja);
    p.v = [0.7 * p.v[0] + 0.3 * (b[0] - a[0]) / dt, 0.7 * p.v[1] + 0.3 * (b[1] - a[1]) / dt];
    p.caja = caja; p.t = t; p.tVisto = t; p.aciertos++; p.detIdx = i;
  }
}
