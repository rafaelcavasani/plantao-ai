"""Pipeline completo do worker: suporte, roteamento, idempotência, handoff e envio (T040–T046, T058–T062)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from apps.worker.jobs import processar_mensagem
from core.config import settings
from core.handoff.textos import TEXTO_HANDOFF, TEXTO_NAO_TEXTO
from core.llm.ports import Finalidade, LLMError
from tests.fakes.channel import FakeChannel
from tests.fakes.conhecimento import inserir_conhecimento, json_roteador, json_suporte
from tests.fakes.llm import FakeLLMClient
from tests.fakes.pipeline import JID, consultar, contexto, marcar_handoff, mensagem_humana, receber

BASE = {
    "faq.md": [
        "Horário de atendimento: aos sábados abrimos das 8h às 12h.",
        "Estacionamento gratuito.",
    ]
}
RESPOSTA = "Aos sábados atendemos das 8h às 12h."


async def _preparar(db: AsyncEngine, tenant: uuid.UUID) -> None:
    await inserir_conhecimento(db, tenant, BASE)


def _llm_feliz(n: int = 1) -> FakeLLMClient:
    return FakeLLMClient(
        {
            Finalidade.ROTEADOR: [json_roteador("suporte", 0.95)] * n,
            Finalidade.SUPORTE: [json_suporte(RESPOSTA, 0.95)] * n,
        }
    )


async def _job(tenant: uuid.UUID, message_id: uuid.UUID, ctx: dict) -> str:  # type: ignore[type-arg]
    return await processar_mensagem(ctx, str(tenant), str(message_id), "corr-1")


# --- US1: resposta fundamentada ---------------------------------------------------------------
async def test_responde_com_base_na_base_e_registra_tudo(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _preparar(db, tenant_a)
    mid, cid = await receber(tenant_a)
    canal = FakeChannel()
    llm = _llm_feliz()
    assert await _job(tenant_a, mid, contexto(llm, canal)) == "respondida"

    assert canal.enviadas == [(JID, RESPOSTA)]  # o contato é descriptografado só para enviar
    resposta = (await consultar(db, "SELECT * FROM messages WHERE responde_a = :m", m=mid))[0]
    assert resposta.remetente == "agente" and resposta.conteudo == RESPOSTA
    assert resposta.status_envio == "enviada" and resposta.conversation_id == cid
    lead = (
        await consultar(
            db, "SELECT intencao, intencao_confianca FROM messages WHERE id = :m", m=mid
        )
    )[0]
    assert lead.intencao == "suporte" and lead.intencao_confianca == 0.95
    conversa = (
        await consultar(db, "SELECT status, agente_atual FROM conversations WHERE id = :c", c=cid)
    )[0]
    assert (conversa.status, conversa.agente_atual) == ("aberta", "support")
    assert await consultar(db, "SELECT 1 FROM handoff_log") == []
    assert llm.finalidades == [Finalidade.ROTEADOR, Finalidade.SUPORTE]


async def test_historico_vai_para_o_prompt(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    await _preparar(db, tenant_a)
    await receber(tenant_a, "Olá, bom dia!")
    mid, _ = await receber(tenant_a)
    llm = _llm_feliz()
    await _job(tenant_a, mid, contexto(llm))
    assert "Olá, bom dia!" in llm.chamadas[0]["mensagens"][1]["content"]


# --- US1/US4: idempotência --------------------------------------------------------------------
async def test_reentrega_do_job_nao_responde_duas_vezes(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _preparar(db, tenant_a)
    mid, _ = await receber(tenant_a)
    canal = FakeChannel()
    ctx = contexto(_llm_feliz(2), canal)
    assert await _job(tenant_a, mid, ctx) == "respondida"
    assert await _job(tenant_a, mid, ctx) == "ja_respondida"
    assert len(canal.enviadas) == 1
    assert len(await consultar(db, "SELECT 1 FROM messages WHERE responde_a = :m", m=mid)) == 1


async def test_jobs_concorrentes_geram_uma_unica_resposta(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _preparar(db, tenant_a)
    mid, _ = await receber(tenant_a)
    canal = FakeChannel()
    ctx = contexto(_llm_feliz(2), canal)
    resultados = await asyncio.gather(_job(tenant_a, mid, ctx), _job(tenant_a, mid, ctx))
    assert sorted(resultados) == ["ja_respondida", "respondida"]
    assert len(canal.enviadas) == 1
    assert len(await consultar(db, "SELECT 1 FROM messages WHERE responde_a = :m", m=mid)) == 1


async def test_mensagem_inexistente(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    assert await _job(tenant_a, uuid.uuid4(), contexto(FakeLLMClient())) == "mensagem_inexistente"


async def test_job_de_um_tenant_nao_enxerga_mensagem_de_outro(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    mid, _ = await receber(tenant_a)
    llm = FakeLLMClient()
    assert await _job(tenant_b, mid, contexto(llm)) == "mensagem_inexistente"
    assert (
        llm.chamadas == []
        and await consultar(db, "SELECT 1 FROM messages WHERE responde_a IS NOT NULL") == []
    )


# --- Falhas de envio --------------------------------------------------------------------------
async def test_falha_no_envio_mantem_a_resposta_com_status_falha(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _preparar(db, tenant_a)
    mid, _ = await receber(tenant_a)
    assert (
        await _job(tenant_a, mid, contexto(_llm_feliz(), FakeChannel(falhar=True))) == "respondida"
    )
    resposta = (
        await consultar(
            db, "SELECT conteudo, status_envio FROM messages WHERE responde_a = :m", m=mid
        )
    )[0]
    assert resposta.conteudo == RESPOSTA and resposta.status_envio == "falha"


# --- US2: roteamento --------------------------------------------------------------------------
@pytest.mark.parametrize("intencao", ["venda", "agendamento", "cobranca", "outro"])
async def test_outras_intencoes_viram_handoff_com_intencao_registrada(
    db: AsyncEngine, tenant_a: uuid.UUID, intencao: str
) -> None:
    mid, cid = await receber(tenant_a, "Quero marcar um horário")
    canal = FakeChannel()
    llm = FakeLLMClient({Finalidade.ROTEADOR: [json_roteador(intencao, 0.9, ["suporte"])]})
    assert await _job(tenant_a, mid, contexto(llm, canal)) == "handoff"
    lead = (
        await consultar(
            db,
            "SELECT intencao, intencao_confianca, intencoes_secundarias FROM messages WHERE id=:m",
            m=mid,
        )
    )[0]
    assert (lead.intencao, lead.intencoes_secundarias) == (intencao, ["suporte"])
    log = (await consultar(db, "SELECT motivo FROM handoff_log WHERE conversation_id=:c", c=cid))[0]
    assert log.motivo == f"intencao_sem_agente:{intencao}"
    assert canal.enviadas == [(JID, TEXTO_HANDOFF)] and llm.embeds == []


async def test_confianca_baixa_do_roteador_cai_no_suporte(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _preparar(db, tenant_a)
    mid, _ = await receber(tenant_a)
    llm = FakeLLMClient(
        {
            Finalidade.ROTEADOR: [json_roteador("venda", 0.3)],
            Finalidade.SUPORTE: [json_suporte(RESPOSTA, 0.95)],
        }
    )
    assert await _job(tenant_a, mid, contexto(llm)) == "respondida"


# --- US3: handoff -----------------------------------------------------------------------------
async def test_palavra_gatilho_sem_chamar_llm(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    mid, cid = await receber(tenant_a, "Vou chamar o PROCON!")
    canal, llm = FakeChannel(), FakeLLMClient()
    assert await _job(tenant_a, mid, contexto(llm, canal)) == "handoff"
    assert llm.chamadas == [] and llm.embeds == []
    log = (await consultar(db, "SELECT motivo, message_id FROM handoff_log"))[0]
    assert log.motivo == "palavra_gatilho:procon" and log.message_id == mid
    conversa = (
        await consultar(
            db, "SELECT status, agente_atual, handoff_em FROM conversations WHERE id=:c", c=cid
        )
    )[0]
    assert (conversa.status, conversa.agente_atual) == (
        "handoff",
        "humano",
    ) and conversa.handoff_em is not None
    assert canal.enviadas == [(JID, TEXTO_HANDOFF)]


async def test_audio_recebe_texto_proprio_e_vai_para_humano(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    mid, _ = await receber(tenant_a, "", tipo="nao_texto")
    canal = FakeChannel()
    assert await _job(tenant_a, mid, contexto(FakeLLMClient(), canal)) == "handoff"
    assert canal.enviadas == [(JID, TEXTO_NAO_TEXTO)]
    assert (await consultar(db, "SELECT motivo FROM handoff_log"))[0].motivo == "nao_texto"


async def test_falha_do_llm_vira_handoff_sem_expor_erro(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    mid, _ = await receber(tenant_a)
    canal = FakeChannel()
    llm = FakeLLMClient({Finalidade.ROTEADOR: [LLMError("timeout")]})
    assert await _job(tenant_a, mid, contexto(llm, canal)) == "handoff"
    assert (await consultar(db, "SELECT motivo FROM handoff_log"))[0].motivo == "falha_llm"
    assert canal.enviadas == [(JID, TEXTO_HANDOFF)]


async def test_falha_de_embedding_vira_handoff(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    mid, _ = await receber(tenant_a)
    llm = FakeLLMClient({Finalidade.ROTEADOR: [json_roteador()]}, falhar_embedding=True)
    assert await _job(tenant_a, mid, contexto(llm)) == "handoff"
    assert (await consultar(db, "SELECT motivo FROM handoff_log"))[0].motivo == "falha_embedding"


async def test_pergunta_fora_da_base_vira_handoff(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    await _preparar(db, tenant_a)
    mid, _ = await receber(tenant_a, "Vocês vendem pizza vegana?")
    llm = FakeLLMClient({Finalidade.ROTEADOR: [json_roteador()]})
    assert await _job(tenant_a, mid, contexto(llm)) == "handoff"
    assert (await consultar(db, "SELECT motivo FROM handoff_log"))[
        0
    ].motivo == "sem_resposta_na_base"
    assert llm.finalidades == [Finalidade.ROTEADOR]


async def test_guardrail_de_saida_bloqueia_valor_inventado(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _preparar(db, tenant_a)
    mid, _ = await receber(tenant_a)
    canal = FakeChannel()
    llm = FakeLLMClient(
        {
            Finalidade.ROTEADOR: [json_roteador()],
            Finalidade.SUPORTE: [json_suporte("A consulta custa R$ 999,00.", 0.95)],
        }
    )
    assert await _job(tenant_a, mid, contexto(llm, canal)) == "handoff"
    assert (await consultar(db, "SELECT motivo FROM handoff_log"))[0].motivo.startswith(
        "valor_nao_fundamentado"
    )
    assert canal.enviadas == [(JID, TEXTO_HANDOFF)]  # a resposta inventada nunca chega ao cliente


async def test_durante_handoff_o_agente_fica_em_silencio(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _preparar(db, tenant_a)
    mid1, cid = await receber(tenant_a)
    await marcar_handoff(db, cid, minutos_atras=5)
    mid2, _ = await receber(tenant_a, "E aí, alguém aí?")
    canal, llm = FakeChannel(), FakeLLMClient()
    assert await _job(tenant_a, mid2, contexto(llm, canal)) == "handoff_ativo"
    assert canal.enviadas == [] and llm.chamadas == [] and llm.embeds == []
    assert await consultar(db, "SELECT 1 FROM messages WHERE responde_a = :m", m=mid2) == []
    assert mid1 != mid2


async def test_handoff_expira_apos_o_ttl_sem_atividade_humana(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _preparar(db, tenant_a)
    _, cid = await receber(tenant_a, "primeira")
    await marcar_handoff(db, cid, minutos_atras=settings.handoff_ttl_minutes + 5)
    mid, _ = await receber(tenant_a)
    assert await _job(tenant_a, mid, contexto(_llm_feliz())) == "respondida"
    conversa = (
        await consultar(
            db, "SELECT status, agente_atual, handoff_em FROM conversations WHERE id=:c", c=cid
        )
    )[0]
    assert (conversa.status, conversa.agente_atual, conversa.handoff_em) == (
        "aberta",
        "support",
        None,
    )


async def test_atividade_humana_recente_estende_o_handoff(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    _, cid = await receber(tenant_a, "primeira")
    await marcar_handoff(db, cid, minutos_atras=settings.handoff_ttl_minutes + 30)
    await mensagem_humana(db, tenant_a, cid, minutos_atras=10)
    mid, _ = await receber(tenant_a)
    assert await _job(tenant_a, mid, contexto(FakeLLMClient())) == "handoff_ativo"


async def test_handoff_com_atividade_humana_antiga_tambem_expira(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _preparar(db, tenant_a)
    _, cid = await receber(tenant_a, "primeira")
    await marcar_handoff(db, cid, minutos_atras=300)
    await mensagem_humana(db, tenant_a, cid, minutos_atras=settings.handoff_ttl_minutes + 10)
    mid, _ = await receber(tenant_a)
    assert await _job(tenant_a, mid, contexto(_llm_feliz())) == "respondida"
