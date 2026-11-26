// La marioneta (persona controlada con el teclado) produce movimientos que AURA reconoce bien.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { Marioneta, ACCIONES } from "../js/marioneta.js";
import { ClasificadorEstados } from "../js/clasificador.js";
import { OneEuroFilter } from "../js/one_euro.js";

const cfg = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "datos", "config.json"), "utf8"));

// guion: lista de [segundos, acción, "presionar"|"soltar"]; devuelve la etiqueta en cada instante
function simular(guion, duracion, fps = 30, x0 = 2.4) {
  const m = new Marioneta(); m.x = x0;
  const cl = new ClasificadorEstados(cfg.clasificacion, cfg.alertas, 1.70);
  const f = new OneEuroFilter(cfg.one_euro.min_cutoff, cfg.one_euro.beta, cfg.one_euro.d_cutoff);
  const out = [], eventos = [], alertas = [];
  let g = 0;
  for (let i = 0; i < duracion * fps; i++) {
    const t = i / fps;
    while (g < guion.length && guion[g][0] <= t) { const [, acc, tipo] = guion[g++]; tipo === "soltar" ? m.soltar(acc) : m.presionar(acc); }
    const { kps, scores, caja } = m.actualizar(1 / fps);
    const plano = f.filtrar(kps.flat(), t);
    const o = cl.actualizar(t, Array.from({ length: 17 }, (_, j) => [plano[2 * j], plano[2 * j + 1]]), scores, caja);
    out.push([t, o.estado]); eventos.push(...(o.eventos || [])); alertas.push(...(o.alertas || []));
  }
  const frac = (estado, a, b) => { const s = out.filter(([t]) => t >= a && t < b); return s.filter(([, e]) => e === estado).length / s.length; };
  return { out, frac, eventos, alertas, m };
}

test("menú: cada acción tiene tecla, nombre y lo que debe detectar", () => {
  for (const a of ACCIONES) assert.ok(a.teclas.length && a.nombre && a.detecta);
});

test("caminar con → y luego quedarse quieto", () => {
  const r = simular([[1.5, "derecha"], [4.5, "derecha", "soltar"]], 6.5, 30, 0.6);
  assert.ok(r.frac("caminando", 2.5, 4.5) > 0.9, r.frac("caminando", 2.5, 4.5));
  assert.ok(r.frac("de_pie", 5.5, 6.5) > 0.9);
  assert.ok(r.m.x > 0.6 + 2.8);                                 // avanzó ~3.2 m a 1.1 m/s
});

test("saltar con ↑", () => {
  const r = simular([[2, "saltar"]], 5);
  assert.ok(r.out.some(([, e]) => e === "saltando"));
  assert.ok(!r.eventos.some((e) => e.tipo === "caida"));
});

test("caerse con C: POSIBLE CAÍDA y luego levantarse con L", () => {
  const r = simular([[2, "caer"], [9, "levantarse"]], 14);
  assert.equal(r.eventos.filter((e) => e.tipo === "caida").length, 1);
  assert.equal(r.alertas[0].mensaje, "POSIBLE CAÍDA");
  assert.ok(r.frac("en_el_suelo", 6.5, 9) > 0.9);              // "caida" se muestra 3 s tras confirmarse
  assert.ok(r.frac("de_pie", 12.5, 14) > 0.9);
});

test("acostarse despacio con A no es una caída", () => {
  const r = simular([[2, "acostarse"]], 9);
  assert.ok(r.frac("en_el_suelo", 6.5, 9) > 0.9);
  assert.ok(!r.eventos.some((e) => e.tipo === "caida"));
});

test("sentarse con S y levantarse con S", () => {
  const r = simular([[2, "sentarse"], [7, "sentarse"]], 10);
  assert.ok(r.frac("sentado", 4, 7) > 0.9);
  assert.ok(r.frac("de_pie", 9, 10) > 0.9);
});

test("sentadillas (E) y saltos de tijera (J) no se confunden con caídas", () => {
  const r = simular([[1.5, "sentadillas"], [12, "sentadillas"], [13, "tijeras"], [19, "tijeras"]], 21);
  assert.ok(!r.eventos.some((e) => e.tipo === "caida"));
  const enSentadillas = new Set(r.out.filter(([t]) => t > 3 && t < 12).map(([, e]) => e));
  assert.ok(enSentadillas.size >= 2, [...enSentadillas].join(","));  // alterna estados
  assert.ok(r.out.some(([t, e]) => t > 13 && t < 19 && e === "saltando"));
});

test("rutina automática (R) recorre varios estados y la caída", () => {
  const r = simular([[0.5, "rutina"]], 60);
  const vistos = new Set(r.out.map(([, e]) => e));
  for (const e of ["caminando", "saltando", "sentado", "caida", "en_el_suelo", "de_pie"]) assert.ok(vistos.has(e), `falta ${e}: ${[...vistos]}`);
});
