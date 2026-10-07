import { test } from "node:test";
import assert from "node:assert/strict";
import { arcosDoDonut, escalaDoEixo, largurasDoFunil, caminhoSuave, rotuloDoEixo } from "../js/graficos.js";

test("donut: os arcos fecham exatamente a circunferência", () => {
  const arcos = arcosDoDonut([9, 3, 2, 1], 70);
  const C = 2 * Math.PI * 70;
  const soma = arcos.reduce((a, x) => a + x.comprimento, 0);
  assert.ok(Math.abs(soma - C) < 1e-9);
  assert.ok(arcos.every((a) => Math.abs(a.circunferencia - C) < 1e-9));
});

test("donut: deslocamento é o acumulado negativo dos arcos anteriores", () => {
  const arcos = arcosDoDonut([46, 28, 16, 10], 70);
  assert.equal(Math.abs(arcos[0].deslocamento), 0);
  let acumulado = 0;
  for (const a of arcos) {
    assert.ok(Math.abs(a.deslocamento + acumulado) < 1e-9);
    acumulado += a.comprimento;
  }
  assert.deepEqual(arcos.map((a) => Math.round(a.fracao * 100)), [46, 28, 16, 10]);
});

test("donut sem dados não quebra", () => {
  const arcos = arcosDoDonut([0, 0], 70);
  assert.ok(arcos.every((a) => a.comprimento === 0));
});

test("funil: escala relativa por etapa e nenhuma barra abaixo de 20%", () => {
  for (const n of [2, 3, 4, 5, 8]) {
    const l = largurasDoFunil(n);
    assert.equal(l.length, n);
    assert.equal(l[0], 100);
    assert.ok(l.every((v) => v >= 20), `${n}: ${l}`);
    assert.deepEqual([...l].sort((a, b) => b - a), l, "decrescente");
  }
  assert.deepEqual(largurasDoFunil(1), [100]);
});

test("eixo: o menor passo bonito que cobre o máximo", () => {
  assert.deepEqual(escalaDoEixo(0), { passo: 1, topo: 4, divisoes: 4 });
  assert.equal(escalaDoEixo(3380).topo, 4000);
  assert.equal(escalaDoEixo(14.3).topo, 16);
  assert.equal(escalaDoEixo(106).topo, 120); // passo 30
  for (const max of [1, 7, 99, 250, 3380, 99999]) {
    const e = escalaDoEixo(max);
    assert.ok(e.topo >= max, `${max}`);
    assert.ok(e.topo < max * 2.6 + 4, `${max} -> ${e.topo}`);
  }
});

test("rótulos do eixo", () => {
  assert.equal(rotuloDoEixo(500), "500");
  assert.equal(rotuloDoEixo(1500), "1,5k");
  assert.equal(rotuloDoEixo(20000), "20k");
  assert.equal(rotuloDoEixo(0), "0");
  assert.equal(rotuloDoEixo(2500000), "2.5M");
});

test("caminho suave começa em M e liga os pontos por curvas", () => {
  assert.equal(caminhoSuave([]), "");
  const d = caminhoSuave([[0, 10], [10, 20], [20, 5]]);
  assert.ok(d.startsWith("M0 10 C"));
  assert.equal((d.match(/C/g) ?? []).length, 2);
});
