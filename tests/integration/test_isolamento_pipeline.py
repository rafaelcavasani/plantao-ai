"""Isolamento no fluxo completo: webhook, fila e worker com canal e LLM falsos (T058, US3 cenários 2 a 5).

Duas empresas recebem mensagens pelo webhook; os jobs enfileirados são executados pelo worker. Banco e Redis são
reais/falsos como nos demais testes; nada sai para a internet.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import AsyncEngine

from apps.worker.jobs import processar_mensagem
from core.llm.ports import Finalidade
from tests.conftest import ConexaoCriada, criar_conexao, criar_tenant
from tests.fakes.channel import FakeChannel, FakeQueue
from tests.fakes.conhecimento import inserir_conhecimento, json_roteador, json_suporte
from tests.fakes.llm import FakeLLMClient
from tests.fakes.pipeline import JID, consultar, contexto
from tests.fakes.webhook import PERGUNTA, enviar, rodar_fila

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("relogio_do_limite")]

RESPOSTA_A = "Aos sábados atendemos das 8h às 12h."
RESPOSTA_B = "Aos sábados atendemos das 7h às 13h."


@dataclass
class Empresa:
    tenant_id: uuid.UUID
    conexao: ConexaoCriada
    llm: FakeLLMClient
    resposta: str

    def ctx(self, canal: FakeChannel) -> dict[str, Any]:
        return contexto(self.llm, canal)


def _llm(resposta: str, n: int = 40) -> FakeLLMClient:
    return FakeLLMClient(
        {
            Finalidade.ROTEADOR: [json_roteador("suporte", 0.95)] * n,
            Finalidade.SUPORTE: [json_suporte(resposta, 0.95)] * n,
        }
    )


async def _empresa(
    db: AsyncEngine, nome: str, instancia: str, resposta: str, horario: str, **config: object
) -> Empresa:
    tenant_id = await criar_tenant(db, nome, **config)
    await inserir_conhecimento(
        db, tenant_id, {"faq.md": [f"Horário de atendimento: aos sábados abrimos das {horario}."]}
    )
    conexao = await criar_conexao(db, tenant_id, instance_name=instancia)
    return Empresa(tenant_id, conexao, _llm(resposta), resposta)


@pytest_asyncio.fixture
async def a(db: AsyncEngine) -> Empresa:
    return await _empresa(db, "Clínica A", "inst-a", RESPOSTA_A, "8h às 12h")


@pytest_asyncio.fixture
async def b(db: AsyncEngine) -> Empresa:
    return await _empresa(db, "Clínica B", "inst-b", RESPOSTA_B, "7h às 13h")


async def _enviar(
    cliente: httpx.AsyncClient,
    empresa: Empresa,
    id: str = "ID-1",
    texto: str = PERGUNTA,
) -> str:
    return await enviar(cliente, empresa.conexao, id, texto)


_rodar_fila = rodar_fila


# --- FR-024: mesmo telefone em duas empresas ----------------------------------------------------
async def test_mesmo_telefone_em_a_e_b_gera_duas_conversas_sem_historico_compartilhado(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, a: Empresa, b: Empresa
) -> None:
    canal = FakeChannel()
    ctxs = {a.tenant_id: a.ctx(canal), b.tenant_id: b.ctx(canal)}
    await _enviar(cliente, a, "A1", "Oi, aqui é a Maria da empresa A")
    await _rodar_fila(fila, ctxs)
    await _enviar(cliente, b, "B1", PERGUNTA)
    await _rodar_fila(fila, ctxs)

    conversas = await consultar(db, "SELECT id, tenant_id FROM conversations")
    assert {c.tenant_id for c in conversas} == {a.tenant_id, b.tenant_id} and len(conversas) == 2
    prompt_b = " ".join(str(c["mensagens"]) for c in b.llm.chamadas)
    assert "Maria da empresa A" not in prompt_b and "Aos sábados atendemos das 8h" not in prompt_b
    assert [m for m in canal.envios if m[0] == "inst-b"][0][2] == RESPOSTA_B


# --- FR-025: mesmo external_id ------------------------------------------------------------------
async def test_mesmo_external_id_e_processado_e_respondido_uma_vez_por_empresa(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, a: Empresa, b: Empresa
) -> None:
    canal = FakeChannel()
    ctxs = {a.tenant_id: a.ctx(canal), b.tenant_id: b.ctx(canal)}
    assert await _enviar(cliente, a, "MESMO") == "queued"
    assert await _enviar(cliente, b, "MESMO") == "queued"
    assert await _enviar(cliente, a, "MESMO") == "duplicate"
    resultados = await _rodar_fila(fila, ctxs)

    assert sorted(r for _, r, _ in resultados) == ["respondida", "respondida"]
    assert sorted(i for i, _, _ in canal.envios) == ["inst-a", "inst-b"]
    respostas = await consultar(db, "SELECT tenant_id FROM messages WHERE responde_a IS NOT NULL")
    assert sorted(str(r.tenant_id) for r in respostas) == sorted(
        [str(a.tenant_id), str(b.tenant_id)]
    )


# --- FR-026 / SC-006: limite de uma empresa não afeta a outra -----------------------------------
async def test_limite_excedido_em_a_nao_afeta_b_e_as_chaves_do_redis_sao_separadas(
    cliente: httpx.AsyncClient,
    fila: FakeQueue,
    redis: FakeAsyncRedis,
    db: AsyncEngine,
    b: Empresa,
) -> None:
    a = await _empresa(
        db, "Limite 1", "inst-limite", RESPOSTA_A, "8h às 12h", limite_mensagens_por_minuto=1
    )
    canal = FakeChannel()
    ctxs = {a.tenant_id: a.ctx(canal), b.tenant_id: b.ctx(canal)}

    estados_a = [await _enviar(cliente, a, f"A{i}") for i in range(5)]
    estados_b = [await _enviar(cliente, b, f"B{i}") for i in range(10)]
    assert estados_a == ["queued", *["rate_limited"] * 4]
    assert estados_b == ["queued"] * 10

    resultados = await _rodar_fila(fila, ctxs)
    de_b = [(r, t) for tenant, r, t in resultados if tenant == b.tenant_id]
    assert len(de_b) == 10 and all(r == "respondida" for r, _ in de_b)
    assert sum(t <= 10.0 for _, t in de_b) / len(de_b) >= 0.9  # SC-006

    chaves = [k.decode() for k in await redis.keys("rl:*")]
    assert any(k.startswith(f"rl:{a.tenant_id}:") for k in chaves)
    assert any(k.startswith(f"rl:{b.tenant_id}:") for k in chaves)
    assert all(k.startswith((f"rl:{a.tenant_id}:", f"rl:{b.tenant_id}:")) for k in chaves)
    assert int(await redis.get(next(k for k in chaves if str(a.tenant_id) in k)) or 0) == 5
    assert int(await redis.get(next(k for k in chaves if str(b.tenant_id) in k)) or 0) == 10


# --- FR-027: falha de canal em A não afeta B ----------------------------------------------------
async def test_falha_de_canal_em_a_vira_handoff_so_em_a_e_b_segue_normal(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, a: Empresa, b: Empresa
) -> None:
    canal = FakeChannel(falhar_instancias={"inst-a"})
    ctxs = {a.tenant_id: a.ctx(canal), b.tenant_id: b.ctx(canal)}
    await _enviar(cliente, a, "A1")
    await _enviar(cliente, b, "B1")
    resultados = {tenant: r for tenant, r, _ in await _rodar_fila(fila, ctxs)}

    assert resultados == {a.tenant_id: "falha_canal", b.tenant_id: "respondida"}
    handoffs = await consultar(db, "SELECT tenant_id, motivo FROM handoff_log")
    assert [(h.tenant_id, h.motivo) for h in handoffs] == [(a.tenant_id, "falha_canal")]
    conversas = await consultar(db, "SELECT tenant_id, status FROM conversations")
    assert {c.tenant_id: c.status for c in conversas} == {
        a.tenant_id: "handoff",
        b.tenant_id: "aberta",
    }
    assert canal.envios == [("inst-b", JID, RESPOSTA_B)]


# --- cenário 5: job com tenant trocado ------------------------------------------------------------
async def test_job_com_tenant_trocado_devolve_mensagem_inexistente_e_nao_chama_o_llm(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, a: Empresa, b: Empresa
) -> None:
    await _enviar(cliente, a, "A1")
    ((_, (_tenant, mensagem, correlacao), _kw),) = fila.jobs
    canal = FakeChannel()

    resultado = await processar_mensagem(b.ctx(canal), str(b.tenant_id), mensagem, correlacao)

    assert resultado == "mensagem_inexistente"
    assert b.llm.chamadas == [] and canal.envios == []
    assert await consultar(db, "SELECT 1 FROM messages WHERE responde_a IS NOT NULL") == []
