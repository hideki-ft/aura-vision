// Comprueba que la versión web (JavaScript) da los mismos resultados que la versión Python.
// Ejecutar:  node --test web/tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { ClasificadorEstados } from "../js/clasificador.js";
import { OneEuroFilter } from "../js/one_euro.js";
import { CanalWifi, espectro, calcularV, frecuenciaEsperada, giroDeFase, SimuladorWifi } from "../js/wifi.js";

const aqui = dirname(fileURLToPath(import.meta.url));
const casos = JSON.parse(readFileSync(join(aqui, "casos.json"), "utf8"));
const cfg = JSON.parse(readFileSync(join(aqui, "..", "datos", "config.json"), "utf8"));

for (const [nombre, c] of Object.entries(casos.clasificador)) {
  test(`clasificador igual que Python: ${nombre}`, () => {
    const cl = new ClasificadorEstados(cfg.clasificacion, cfg.alertas, 1.70);
    const f = new OneEuroFilter(cfg.one_euro.min_cutoff, cfg.one_euro.beta, cfg.one_euro.d_cutoff);
    const estados = [], eventos = [], alertas = [];
    c.t.forEach((t, i) => {
      const plano = f.filtrar(c.kps[i].flat(), t);
      const kps = Array.from({ length: 17 }, (_, j) => [plano[2 * j], plano[2 * j + 1]]);
      const o = cl.actualizar(t, kps, c.scores[i], c.cajas[i]);
      estados.push(o.estado); eventos.push(...(o.eventos || []).map((e) => e.tipo)); alertas.push(...(o.alertas || []).map((a) => a.mensaje));
    });
    const iguales = estados.filter((e, i) => e === c.estados[i]).length / estados.length;
    assert.ok(iguales >= 0.99, `coincidencia ${iguales}`);
    assert.deepEqual(eventos, c.eventos);
    assert.deepEqual(alertas, c.alertas);
    if (c.ultimo_salto) assert.ok(Math.abs(cl.ultimoSalto.altura_m - c.ultimo_salto.altura_m) < 0.005);
  });
}

test("canal: |H| y fase iguales que Python (5 caminos)", () => {
  const canal = new CanalWifi(cfg.wifi);
  casos.canal.P.forEach((p, i) => {
    const { re, im } = canal.H(p);
    re.forEach((r, k) => {
      assert.ok(Math.abs(Math.hypot(r, im[k]) - casos.canal.absH[i][k]) < 1e-7);
      assert.ok(Math.abs(Math.atan2(im[k], r) - casos.canal.argH[i][k]) < 1e-6);
    });
  });
  const v = canal.H(null);
  v.re.forEach((r, k) => assert.ok(Math.abs(Math.hypot(r, v.im[k]) - casos.canal.absH_vacia[k]) < 1e-7));
});

test("con |Γ| = 0 la persona no cambia H", () => {
  const canal = new CanalWifi(cfg.wifi); canal.contraste = 0;
  const vacia = canal.H(null);
  for (const p of [[1, 0.5], [1, 1.5], [2.5, 2]]) {
    const h = canal.H(p); h.re.forEach((r, k) => assert.ok(Math.abs(r - vacia.re[k]) < 1e-12 && Math.abs(h.im[k] - vacia.im[k]) < 1e-12));
  }
});

test("Welch igual que scipy", () => {
  const { f, P } = espectro(casos.welch.A, 100, 128);
  assert.equal(f.length, casos.welch.f.length);
  P.forEach((p, i) => assert.ok(Math.abs(p - casos.welch.P[i]) <= 1e-9 + 1e-6 * Math.abs(casos.welch.P[i]), `i=${i} ${p} vs ${casos.welch.P[i]}`));
});

test("V, f = 2v/λ y Δφ", () => {
  assert.equal(calcularV(Array.from({ length: 50 }, () => new Array(26).fill(1))), 0);
  assert.ok(Math.abs(frecuenciaEsperada(1, 0.125) - 16) < 1e-12);
  assert.ok(Math.abs(giroDeFase(0.0625, 0.125) - 2 * Math.PI) < 1e-12);
  const w = { ...cfg.wifi, router_m: [0.05, 1.5], receptor_m: [0.05, 1.45], ruido_sigma: 0.001 };
  const s = new SimuladorWifi(w); let m;
  for (let i = 0; i < 90; i++) { const t = i / 15; s.alimentar(t, [1 + 0.5 * t, 1.5]); m = s.metricas(); }
  assert.ok(Math.abs(m.pico_hz - m.f_esperada_hz) < 1.0, `pico ${m.pico_hz} vs ${m.f_esperada_hz}`);
});
