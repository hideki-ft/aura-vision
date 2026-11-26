// Utilidades numéricas (equivalentes a las de numpy que usa la versión Python).
export const finito = (x) => typeof x === "number" && Number.isFinite(x);
export function mediana(v) {
  const a = v.filter(finito).sort((x, y) => x - y);
  if (!a.length) return NaN;
  const m = a.length >> 1;
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}
export function percentil(v, q) {           // interpolación lineal (como numpy)
  const a = v.filter(finito).sort((x, y) => x - y);
  if (!a.length) return NaN;
  const i = (q / 100) * (a.length - 1), lo = Math.floor(i), hi = Math.ceil(i);
  return a[lo] + (a[hi] - a[lo]) * (i - lo);
}
export const maxFinito = (v) => { const a = v.filter(finito); return a.length ? Math.max(...a) : NaN; };
export const minFinito = (v) => { const a = v.filter(finito); return a.length ? Math.min(...a) : NaN; };
export const media = (v) => { const a = v.filter(finito); return a.length ? a.reduce((s, x) => s + x, 0) / a.length : NaN; };
export const clip = (x, a, b) => Math.min(Math.max(x, a), b);

// Ajuste por mínimos cuadrados de un polinomio de grado g (1 o 2). Devuelve coeficientes [a_g, ..., a_0] como np.polyfit.
export function polyfit(x, y, g) {
  const n = g + 1, A = Array.from({ length: n }, () => new Array(n).fill(0)), b = new Array(n).fill(0);
  for (let i = 0; i < x.length; i++) {
    const p = []; for (let k = 0; k < n; k++) p.push(x[i] ** (g - k));
    for (let r = 0; r < n; r++) { b[r] += p[r] * y[i]; for (let c = 0; c < n; c++) A[r][c] += p[r] * p[c]; }
  }
  for (let c = 0; c < n; c++) {               // eliminación gaussiana con pivoteo
    let piv = c; for (let r = c + 1; r < n; r++) if (Math.abs(A[r][c]) > Math.abs(A[piv][c])) piv = r;
    [A[c], A[piv]] = [A[piv], A[c]]; [b[c], b[piv]] = [b[piv], b[c]];
    for (let r = c + 1; r < n; r++) { const f = A[r][c] / A[c][c]; for (let k = c; k < n; k++) A[r][k] -= f * A[c][k]; b[r] -= f * b[c]; }
  }
  const s = new Array(n).fill(0);
  for (let r = n - 1; r >= 0; r--) { let acc = b[r]; for (let k = r + 1; k < n; k++) acc -= A[r][k] * s[k]; s[r] = acc / A[r][r]; }
  return s;
}

// Números aleatorios normales (Box-Muller)
export function randn() {
  let u = 0, v = 0; while (u === 0) u = Math.random(); while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}
