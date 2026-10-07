import { test } from "node:test";
import assert from "node:assert/strict";
import { visual, ordenarPorGravidade, descricao, gravidadeMaxima, MOTIVOS } from "../js/atencao.js";

test("todo motivo tem ícone e rótulo (cor nunca é o único sinal)", () => {
  for (const [codigo, v] of Object.entries(MOTIVOS)) {
    assert.ok(v.icone && v.rotulo, codigo);
  }
  assert.ok(visual("desconhecido").rotulo);
});

test("ordem: crítica primeiro e depois por nome", () => {
  const ordenado = ordenarPorGravidade([
    { nome: "Zeta", gravidade: "aviso" },
    { nome: "Beta", gravidade: "critica" },
    { nome: "Alfa", gravidade: "aviso" },
  ]);
  assert.deepEqual(ordenado.map((a) => a.nome), ["Beta", "Alfa", "Zeta"]);
});

test("descrição e gravidade máxima", () => {
  const a = [{ detalhe: "sem mensagens há 26 h", gravidade: "aviso" }, { detalhe: "custo em 92%", gravidade: "critica" }];
  assert.equal(descricao(a), "sem mensagens há 26 h; custo em 92%");
  assert.equal(gravidadeMaxima(a), "critica");
  assert.equal(gravidadeMaxima([]), null);
  assert.equal(descricao(null), "");
});
