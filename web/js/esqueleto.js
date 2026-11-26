// Puntos clave COCO (17) y medidas geométricas — igual que aura/vision/esqueleto.py
import { finito, mediana } from "./util.js";
export const ESQUELETO = [[5,6],[5,7],[7,9],[6,8],[8,10],[5,11],[6,12],[11,12],[11,13],[13,15],[12,14],[14,16],[0,1],[0,2],[1,3],[2,4]];
export const FRAC_CADENA = 0.246 + 0.245 + 0.288;
export const FRAC_ALTURA_TOBILLO = 0.039;

// kps: array de 17 [x, y]; scores: 17 valores. Devuelve puntos con NaN donde la confianza es baja.
export const puntosValidos = (kps, scores, umbral) => kps.map((p, j) => (scores[j] >= umbral ? [p[0], p[1]] : [NaN, NaN]));
export function mediaPuntos(xy, idx) {
  const xs = idx.map((i) => xy[i][0]).filter(finito), ys = idx.map((i) => xy[i][1]).filter(finito);
  return [xs.length ? xs.reduce((a, b) => a + b) / xs.length : NaN, ys.length ? ys.reduce((a, b) => a + b) / ys.length : NaN];
}
export function anguloTorso(cad, hom) {
  const vx = hom[0] - cad[0], vy = hom[1] - cad[1];
  return Math.atan2(Math.abs(vx), -vy) * 180 / Math.PI;
}
export function anguloEn(a, b, c) {
  const v1 = [a[0] - b[0], a[1] - b[1]], v2 = [c[0] - b[0], c[1] - b[1]];
  const n = Math.hypot(...v1) * Math.hypot(...v2);
  if (!finito(n) || n < 1e-9) return NaN;
  return Math.acos(Math.min(1, Math.max(-1, (v1[0] * v2[0] + v1[1] * v2[1]) / n))) * 180 / Math.PI;
}
const dist = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1]);
export function estaturaAparente(xy) {
  const piernas = [];
  for (const [a, k, h] of [[15, 13, 11], [16, 14, 12]]) {
    const v = dist(xy[a], xy[k]) + dist(xy[k], xy[h]);
    if (finito(v)) piernas.push(v);
  }
  const tronco = dist(mediaPuntos(xy, [5, 6]), mediaPuntos(xy, [11, 12]));
  if (piernas.length && finito(tronco)) return (piernas.reduce((s, x) => s + x) / piernas.length + tronco) / FRAC_CADENA;
  return NaN;
}
export function cajaDePuntos(kps, scores, umbral = 0.3, margen = 0.15) {
  const p = kps.filter((_, j) => scores[j] >= umbral);
  if (p.length < 4) return null;
  const xs = p.map((q) => q[0]), ys = p.map((q) => q[1]);
  const x1 = Math.min(...xs), x2 = Math.max(...xs), y1 = Math.min(...ys), y2 = Math.max(...ys), w = x2 - x1, h = y2 - y1;
  return [x1 - margen * w, y1 - margen * h - 0.06 * h, x2 + margen * w, y2 + margen * h];
}
export { mediana };
