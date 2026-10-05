"""Registro de uso, custo e handoff por mensagem e conversa (T074, T078; FR-017, FR-018, SC-007)."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from agents.orchestrator.graph import Grafo
from apps.worker.jobs import processar_mensagem
from core.llm.openrouter import OpenRouterClient
from tests.conftest import criar_conexao
from tests.fakes.channel import FakeChannel
from tests.fakes.conhecimento import inserir_conhecimento, json_roteador, json_suporte
from tests.fakes.openrouter import OpenRouterFalso
from tests.fakes.pipeline import consultar, receber

BASE = {"faq.md": ["Horário de atendimento: aos sábados abrimos das 8h às 12h."]}


@pytest_asyncio.fixture(autouse=True)
async def _conexao_a(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    await criar_conexao(db, tenant_a, instance_name="inst-a")


async def _sem_espera(_: float) -> None:
    return None


def _chat(corpo: dict[str, Any]) -> str:
    sistema = corpo["messages"][0]["content"]
    if "classifica a intenção" in sistema:
        return json_roteador("suporte", 0.95)
    return json_suporte("Aos sábados atendemos das 8h às 12h.", 0.95)


async def _rodar(tenant: uuid.UUID, mid: uuid.UUID, falso: OpenRouterFalso) -> str:
    llm = OpenRouterClient(
        api_key="k", base_url="http://gw.test/v1", transport=falso.transport, sleep=_sem_espera
    )
    ctx = {"grafo": Grafo(llm), "channel": FakeChannel()}
    try:
        return await processar_mensagem(ctx, str(tenant), str(mid), "corr-uso")
    finally:
        await llm.aclose()


async def test_cada_mensagem_respondida_tem_uma_linha_por_chamada_de_llm(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await inserir_conhecimento(db, tenant_a, BASE)
    mid, cid = await receber(tenant_a, "Qual o horário de atendimento aos sábados?")
    assert await _rodar(tenant_a, mid, OpenRouterFalso(_chat)) == "respondida"

    chamadas = await consultar(db, "SELECT * FROM llm_calls ORDER BY criado_em")
    assert sorted(c.finalidade for c in chamadas) == ["embedding", "roteador", "suporte"]
    for c in chamadas:
        assert c.conversation_id == cid and c.message_id == mid and c.tenant_id == tenant_a
        assert c.sucesso is True and c.erro is None and c.modelo
        assert c.tokens_entrada > 0 and c.latencia_ms >= 0
    por_finalidade = {c.finalidade: c for c in chamadas}
    assert (
        por_finalidade["roteador"].tokens_saida == 30
        and por_finalidade["suporte"].tokens_saida == 30
    )
    assert por_finalidade["suporte"].custo_usd > Decimal(0)


async def test_custo_por_conversa_e_somavel_com_uma_consulta(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await inserir_conhecimento(db, tenant_a, BASE)
    mid1, cid = await receber(tenant_a, "Qual o horário de atendimento aos sábados?")
    mid2, _ = await receber(tenant_a, "E qual o horário de atendimento aos sábados mesmo?")
    falso = OpenRouterFalso(_chat)
    await _rodar(tenant_a, mid1, falso)
    await _rodar(tenant_a, mid2, falso)
    linha = (
        await consultar(
            db,
            "SELECT count(*) AS n, sum(custo_usd) AS custo, sum(tokens_entrada + tokens_saida) AS tokens "
            "FROM llm_calls WHERE conversation_id = :c",
            c=cid,
        )
    )[0]
    assert linha.n == 6 and linha.custo > 0 and linha.tokens > 0


async def test_falha_do_gateway_e_registrada_e_vira_handoff_com_ids(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    mid, cid = await receber(tenant_a)
    resultado = await _rodar(tenant_a, mid, OpenRouterFalso(lambda corpo: 503))
    assert resultado == "handoff"
    chamada = (await consultar(db, "SELECT * FROM llm_calls"))[0]
    assert chamada.finalidade == "roteador" and chamada.sucesso is False and chamada.erro
    assert chamada.message_id == mid and chamada.conversation_id == cid
    log = (await consultar(db, "SELECT * FROM handoff_log"))[0]
    assert log.motivo == "falha_llm" and log.message_id == mid and log.conversation_id == cid


async def test_handoff_registra_motivo_confianca_e_mensagem(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await inserir_conhecimento(db, tenant_a, BASE)
    mid, cid = await receber(tenant_a, "Qual o horário de atendimento aos sábados?")
    falso = OpenRouterFalso(
        lambda c: (
            json_roteador("suporte", 0.95)
            if "classifica" in c["messages"][0]["content"]
            else json_suporte("ok", 0.4)
        )
    )
    assert await _rodar(tenant_a, mid, falso) == "handoff"
    log = (await consultar(db, "SELECT * FROM handoff_log"))[0]
    assert log.motivo == "confianca_abaixo_do_minimo"
    assert log.confianca_no_momento == pytest.approx(0.4)
    assert log.message_id == mid and log.conversation_id == cid and log.tenant_id == tenant_a


async def test_caminho_deterministico_nao_gera_chamada_de_llm(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    mid, _ = await receber(tenant_a, "Vou ao procon")
    falso = OpenRouterFalso(_chat)
    assert await _rodar(tenant_a, mid, falso) == "handoff"
    assert falso.requests == [] and await consultar(db, "SELECT 1 FROM llm_calls") == []


async def test_prompt_enviado_ao_gateway_nao_contem_telefone_nem_ids_internos(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await inserir_conhecimento(db, tenant_a, BASE)
    mid, cid = await receber(tenant_a, "Qual o horário de atendimento aos sábados?")
    falso = OpenRouterFalso(_chat)
    await _rodar(tenant_a, mid, falso)
    enviado = json.dumps(falso.requests, ensure_ascii=False)
    assert "5511999990000" not in enviado
    assert str(tenant_a) not in enviado and str(cid) not in enviado and str(mid) not in enviado
