// Calibración de 2 puntos del piso → posición en la planta (igual que aura/vision/calibracion.py)
export class Calibracion {
  constructor(c, w) { this.Am = c.punto_A_m; this.Bm = c.punto_B_m; this.Apx = c.pixeles_A; this.Bpx = c.pixeles_B; this.lim = [w.habitacion.ancho_m, w.habitacion.largo_m]; this.pendiente = null; }
  get calibrada() { return !!(this.Apx && this.Bpx); }
  fijar(cual, x, y) { if (cual === "A") this.Apx = [x, y]; else this.Bpx = [x, y]; }
  posicion(xPx, ySueloPx, mPorPx, ancho) {
    const L = Math.hypot(this.Bm[0] - this.Am[0], this.Bm[1] - this.Am[1]);
    let s;
    if (this.calibrada) {
      const ab = [this.Bpx[0] - this.Apx[0], this.Bpx[1] - this.Apx[1]];
      s = ((xPx - this.Apx[0]) * ab[0] + (ySueloPx - this.Apx[1]) * ab[1]) / Math.max(ab[0] ** 2 + ab[1] ** 2, 1e-9);
    } else if (Number.isFinite(mPorPx) && Number.isFinite(xPx) && L > 0) s = 0.5 + (xPx - ancho / 2) * mPorPx / L;
    else return null;
    if (!Number.isFinite(s)) return null;
    s = Math.min(1.1, Math.max(-0.1, s));
    const p = [this.Am[0] + s * (this.Bm[0] - this.Am[0]), this.Am[1] + s * (this.Bm[1] - this.Am[1])];
    return [Math.min(this.lim[0] - 0.05, Math.max(0.05, p[0])), Math.min(this.lim[1] - 0.05, Math.max(0.05, p[1]))];
  }
  aDict() { return { calibrada: this.calibrada, A_px: this.Apx, B_px: this.Bpx, A_m: this.Am, B_m: this.Bm, pendiente: this.pendiente }; }
}
