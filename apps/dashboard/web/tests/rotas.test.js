import { test } from "node:test";
import assert from "node:assert/strict";
import { resolverRota } from "../js/rotas.js";

test("rotas conhecidas", () => {
  assert.deepEqual(resolverRota(""), { tela: "visao-geral" });
  assert.deepEqual(resolverRota("#/"), { tela: "visao-geral" });
  assert.deepEqual(resolverRota("#/empresas"), { tela: "empresas" });
  assert.deepEqual(resolverRota("#/empresas/nova"), { tela: "formulario", modo: "nova" });
  assert.deepEqual(resolverRota("#/empresa/sorriso-vivo"), { tela: "ficha", slug: "sorriso-vivo" });
  assert.deepEqual(resolverRota("#/empresa/sorriso-vivo/editar"), { tela: "formulario", modo: "editar", slug: "sorriso-vivo" });
  assert.deepEqual(resolverRota("#/empresa/sorriso-vivo/conversas"), { tela: "conversas", slug: "sorriso-vivo" });
  const id = "123e4567-e89b-12d3-a456-426614174000";
  assert.deepEqual(resolverRota(`#/empresa/sorriso-vivo/conversas/${id}`), { tela: "conversa", slug: "sorriso-vivo", id });
});

test("barra final é ignorada", () => {
  assert.deepEqual(resolverRota("#/empresas/"), { tela: "empresas" });
});

test("rota desconhecida ou com slug inválido vira 'não encontrada'", () => {
  for (const hash of ["#/x", "#/empresa", "#/empresa/MAIUSCULA", "#/empresa/a_b", "#/empresa/ok/apagar", "#/empresas/outra",
    "#/empresa/ok/conversas/nao-uuid", "#/empresa/%E0%A4%A", `#/empresa/${"a".repeat(64)}`]) {
    assert.deepEqual(resolverRota(hash), { tela: "nao-encontrada" }, hash);
  }
});
