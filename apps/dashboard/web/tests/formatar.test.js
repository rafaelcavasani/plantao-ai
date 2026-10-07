import { test } from "node:test";
import assert from "node:assert/strict";
import * as f from "../js/formatar.js";

const AGORA = Date.parse("2026-10-06T15:00:00Z");
const antes = (minutos) => new Date(AGORA - minutos * 60000).toISOString();

test("números e moeda em pt-BR", () => {
  assert.equal(f.inteiro(55530), "55.530");
  assert.equal(f.decimal(2.345, 2), "2,35");
  assert.equal(f.usd(612.4), "US$ 612,40");
  assert.equal(f.pct(11.84), "11,8%");
  assert.equal(f.inteiro(null), "—");
  assert.equal(f.usd(undefined), "—");
});

test("tempo relativo", () => {
  assert.equal(f.relativo(antes(0), AGORA), "agora");
  assert.equal(f.relativo(antes(3), AGORA), "há 3 min");
  assert.equal(f.relativo(antes(59), AGORA), "há 59 min");
  assert.equal(f.relativo(antes(26 * 60), AGORA), "há 26 h");
  assert.equal(f.relativo(antes(3 * 24 * 60), AGORA), "há 3 dias");
  assert.equal(f.relativo(null, AGORA), "—");
});

test("última mensagem: 'sem mensagens' quando nunca houve", () => {
  assert.deepEqual(f.ultimaMensagem(null, AGORA), { quando: "sem mensagens", quem: null });
  assert.deepEqual(f.ultimaMensagem({ em: antes(8), remetente: "agente" }, AGORA), { quando: "há 8 min", quem: "agente" });
  assert.equal(f.ultimaMensagem({ em: antes(8), remetente: "humano" }, AGORA).quem, "atendente");
  assert.equal(f.ultimaMensagem({ em: antes(8), remetente: "lead" }, AGORA).quem, "contato");
});

test("variações com sinal tipográfico e sem divisão por zero", () => {
  assert.equal(f.variacaoPct(112.4, 100).texto, "+12,4%");
  assert.equal(f.variacaoPct(91.8, 100).texto, "−8,2%");
  assert.equal(f.variacaoPct(10, 0), null);
  assert.equal(f.variacaoPontos(11.8, 13.2).texto, "−1,4 pts");
});

test("datas no fuso de São Paulo", () => {
  assert.equal(f.data("2026-10-06T02:00:00Z"), "05/10/2026"); // 23:00 do dia anterior em UTC-3
  assert.match(f.dataHora("2026-10-06T15:30:00Z"), /06\/10\/2026.*12:30/);
});

test("estados têm texto e classe", () => {
  for (const e of ["ativo", "em_configuracao", "suspenso", "encerrado"]) {
    assert.ok(f.ESTADOS[e] && f.CLASSE_DO_ESTADO[e]);
  }
});
