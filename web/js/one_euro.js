// One Euro Filter (Casiez et al., 2012) — misma lógica que aura/vision/one_euro.py
export class OneEuroFilter {
  constructor(minCutoff = 1.0, beta = 0.0, dCutoff = 1.0) {
    this.minCutoff = minCutoff; this.beta = beta; this.dCutoff = dCutoff;
    this.xPrev = null; this.dxPrev = null; this.tPrev = null;
  }
  reiniciar() { this.xPrev = this.dxPrev = this.tPrev = null; }
  // x: Float64Array (aplanado, p. ej. 34 valores = 17 puntos × 2); t en segundos
  filtrar(x, t) {
    x = Float64Array.from(x);
    if (this.xPrev === null) { this.xPrev = x.slice(); this.dxPrev = new Float64Array(x.length); this.tPrev = t; return x.slice(); }
    const te = t - this.tPrev;
    if (te <= 0) return this.xPrev.slice();
    const out = new Float64Array(x.length);
    const aD = 1 / (1 + (1 / (2 * Math.PI * this.dCutoff)) / te);
    for (let i = 0; i < x.length; i++) {
      const nuevo = Number.isNaN(this.xPrev[i]) && !Number.isNaN(x[i]);
      const xp = nuevo ? x[i] : this.xPrev[i];
      const dx = (x[i] - xp) / te;
      let dxHat = aD * dx + (1 - aD) * (nuevo ? 0 : this.dxPrev[i]);
      const cutoff = this.minCutoff + this.beta * Math.abs(dxHat);
      const a = 1 / (1 + (1 / (2 * Math.PI * cutoff)) / te);
      let xh = a * x[i] + (1 - a) * xp;
      if (Number.isNaN(x[i])) xh = xp;
      out[i] = xh;
      this.dxPrev[i] = Number.isNaN(dxHat) ? 0 : dxHat;
    }
    this.xPrev = out; this.tPrev = t;
    return out.slice();
  }
}
