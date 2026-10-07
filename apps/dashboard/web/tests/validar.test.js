import { test } from "node:test";
import assert from "node:assert/strict";
import * as v from "../js/validar.js";

const horario = { seg: "08:00-18:00", ter: "08:00-18:00", qua: "", qui: "", sex: "", sab: "08:00-12:00", dom: "fechado" };
const base = () => ({
  nome: "Clínica Exemplo", slug: "clinica-exemplo", nicho: "Clínica odontológica", plano: "recepcionista",
  tom_de_voz: "Cordial.", horario: { ...horario },
  limite_desconto_percentual: "10", confianca_minima_handoff: "0.7", limite_mensagens_por_minuto: "20", handoff_ttl_minutos: "120",
});

test("slugificar: sem acento, minúsculas, hífen entre palavras, até 63 caracteres", () => {
  assert.equal(v.slugificar("Clínica Sorriso Vivo"), "clinica-sorriso-vivo");
  assert.equal(v.slugificar("  Pet & Cia!!  "), "pet-cia");
  assert.equal(v.slugificar("Ação Ótica"), "acao-otica");
  assert.equal(v.slugificar("x".repeat(80)).length, 63);
  assert.equal(v.slugificar("***"), "");
  assert.match(v.slugificar("Barbearia Navalha 24h"), v.SLUG_RE);
});

test("slug válido e inválido (mesma regra do servidor)", () => {
  for (const ok of ["abc", "a1b", "clinica-exemplo", "a".repeat(63)]) assert.equal(v.validarSlug(ok), null, ok);
  for (const ruim of ["", "ab", "Maiuscula", "com_underline", "-comeca", "termina-", "dois--hifens", "a".repeat(64), "espaço aqui"]) {
    assert.ok(v.validarSlug(ruim), ruim);
  }
});

test("horário: HH:MM-HH:MM, fechado ou vazio", () => {
  for (const ok of ["08:00-18:00", "00:00-23:59", "fechado", "Fechado", "", "  "]) assert.equal(v.validarHorario(ok), null, ok);
  for (const ruim of ["8h-18h", "25:00-26:00", "08:00-18:60", "08:00 18:00", "08:00-18:00-20:00", "abc"]) {
    assert.ok(v.validarHorario(ruim), ruim);
  }
});

test("faixas numéricas", () => {
  assert.equal(v.validarFaixa("limite_desconto_percentual", "0"), null);
  assert.equal(v.validarFaixa("limite_desconto_percentual", "100"), null);
  assert.ok(v.validarFaixa("limite_desconto_percentual", "101"));
  assert.ok(v.validarFaixa("limite_desconto_percentual", "-1"));
  assert.equal(v.validarFaixa("confianca_minima_handoff", "0,7"), null);
  assert.ok(v.validarFaixa("confianca_minima_handoff", "1.5"));
  assert.equal(v.validarFaixa("limite_mensagens_por_minuto", "6000"), null);
  assert.ok(v.validarFaixa("limite_mensagens_por_minuto", "0"));
  assert.ok(v.validarFaixa("limite_mensagens_por_minuto", "6001"));
  assert.ok(v.validarFaixa("limite_mensagens_por_minuto", "2.5"));
  assert.ok(v.validarFaixa("handoff_ttl_minutos", "1441"));
  assert.ok(v.validarFaixa("handoff_ttl_minutos", ""));
  assert.ok(v.validarFaixa("handoff_ttl_minutos", "abc"));
});

test("segredo de entrega: pelo menos 32 caracteres", () => {
  assert.ok(v.validarSegredo("x".repeat(31)));
  assert.equal(v.validarSegredo("x".repeat(32)), null);
});

test("formulário válido não tem erro", () => {
  assert.deepEqual(v.validarFormulario(base(), { modo: "nova", slugsExistentes: [], instanciasEmUso: [] }), {});
});

test("erros apontam o campo com a mesma chave da API", () => {
  const dados = { ...base(), nome: "", slug: "Ruim_", tom_de_voz: " ", limite_desconto_percentual: "200",
    horario: { ...horario, ter: "8h" },
    conexao: { instancia: "", segredo_entrega: "curto", chave_envio: "" } };
  const e = v.validarFormulario(dados, { modo: "nova" });
  for (const campo of ["nome", "slug", "configuracao.tom_de_voz", "configuracao.horario_funcionamento",
    "configuracao.limite_desconto_percentual", "conexao.instancia", "conexao.segredo_entrega", "conexao.chave_envio"]) {
    assert.ok(e[campo], campo);
  }
  assert.match(e["configuracao.horario_funcionamento"], /^Terça:/);
  assert.equal(v.primeiroCampoComErro(e), "nome");
});

test("slug e instância já usados", () => {
  const e = v.validarFormulario(
    { ...base(), conexao: { instancia: "ocupada", segredo_entrega: "x".repeat(40), chave_envio: "k" } },
    { modo: "nova", slugsExistentes: ["clinica-exemplo"], instanciasEmUso: ["ocupada"] },
  );
  assert.match(e.slug, /Já existe uma empresa com o slug 'clinica-exemplo'/);
  assert.match(e["conexao.instancia"], /já está em uso/);
});

test("na edição o slug não é validado (não muda)", () => {
  assert.deepEqual(v.validarFormulario({ ...base(), slug: "QUALQUER COISA" }, { modo: "editar" }), {});
});

test("triagem de arquivos: formato, tamanho, nome repetido e limite por remessa", () => {
  const arq = (name, size = 100) => ({ name, size });
  const r = v.triarArquivos([arq("a.md"), arq("b.TXT"), arq("c.pdf"), arq("virus.exe"), arq("grande.md", 3 * 1024 * 1024), arq("a.md")]);
  assert.deepEqual(r.aceitos.map((a) => a.name), ["a.md", "b.TXT", "c.pdf"]);
  assert.deepEqual(r.recusados.map((x) => x.motivo), ["formato não suportado", "acima de 2 MB", "nome repetido na remessa"]);
  const ja = Array.from({ length: 9 }, (_, i) => arq(`${i}.md`));
  const c = v.triarArquivos([arq("novo1.md"), arq("novo2.md")], ja);
  assert.equal(c.aceitos.length, 1);
  assert.match(c.recusados[0].motivo, /no máximo 10/);
  assert.equal(v.triarArquivos([arq("limite.md", 2 * 1024 * 1024)]).aceitos.length, 1);
});

test("encerrar: o nome tem que ser exato (maiúsculas e espaços contam)", () => {
  assert.equal(v.nomeConfere("Clínica Exemplo", "Clínica Exemplo"), true);
  for (const errado of ["clínica exemplo", "Clínica Exemplo ", " Clínica Exemplo", "Clinica Exemplo", ""]) {
    assert.equal(v.nomeConfere(errado, "Clínica Exemplo"), false, JSON.stringify(errado));
  }
});
