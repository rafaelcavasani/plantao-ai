"""Agregação do painel contra a contagem direta (spec 004, T017; SC-003, ADR-0008).

Duas empresas com atividade conhecida; o job grava o mesmo que uma contagem manual, de forma idempotente,
sem misturar empresas e sem guardar texto nem contato.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from core.painel.agregacao import recalcular_empresa, recalcular_todas
from db.models import Conversation, HandoffLog, KnowledgeDocument, LLMCall, Message

pytestmark = pytest.mark.integration

H12 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
H13 = H12 + timedelta(hours=1)


def _m(
    t: uuid.UUID,
    c: uuid.UUID,
    quando: datetime,
    remetente: str,
    *,
    tipo: str = "texto",
    intencao: str | None = None,
    status_envio: str | None = None,
    responde_a: uuid.UUID | None = None,
) -> Message:
    return Message(
        id=uuid.uuid4(),
        tenant_id=t,
        conversation_id=c,
        remetente=remetente,
        conteudo="TEXTO-QUE-NAO-PODE-VAZAR",
        tipo=tipo,
        intencao=intencao,
        status_envio=status_envio,
        responde_a=responde_a,
        timestamp=quando,
        external_id=uuid.uuid4().hex if remetente == "lead" else None,
    )


async def popular_a(engine: AsyncEngine, t: uuid.UUID, h12: datetime = H12) -> None:
    h13 = h12 + timedelta(hours=1)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        c1 = Conversation(
            id=uuid.uuid4(),
            tenant_id=t,
            canal="whatsapp",
            contato_hash="h1",
            contato_enc="TELEFONE-SECRETO",
            status="handoff",
            iniciado_em=h12 + timedelta(minutes=5),
        )
        c2 = Conversation(
            id=uuid.uuid4(),
            tenant_id=t,
            canal="whatsapp",
            contato_hash="h2",
            contato_enc="e2",
            status="aberta",
            iniciado_em=h13 + timedelta(minutes=10),
        )
        s.add_all([c1, c2])
        await s.flush()
        m1 = _m(t, c1.id, h12 + timedelta(minutes=10), "lead", intencao="agendar")
        m2 = _m(t, c1.id, h12 + timedelta(minutes=20), "lead", tipo="nao_texto")
        m3 = _m(t, c2.id, h13 + timedelta(minutes=15), "lead")
        s.add_all([m1, m2, m3])
        await s.flush()
        s.add_all(
            [
                _m(t, c1.id, h12 + timedelta(minutes=10, seconds=3), "agente", responde_a=m1.id),
                _m(
                    t,
                    c1.id,
                    h12 + timedelta(minutes=20, seconds=40),
                    "agente",
                    responde_a=m2.id,
                    status_envio="falha",
                ),
                _m(t, c1.id, h12 + timedelta(minutes=30), "humano"),
                _m(t, c2.id, h13 + timedelta(minutes=15, seconds=1), "agente", responde_a=m3.id),
            ]
        )
        s.add_all(
            [
                HandoffLog(
                    tenant_id=t,
                    conversation_id=c1.id,
                    motivo="palavra_gatilho:procon",
                    criado_em=h12 + timedelta(minutes=21),
                ),
                HandoffLog(
                    tenant_id=t,
                    conversation_id=c1.id,
                    motivo="falha_canal",
                    criado_em=h12 + timedelta(minutes=25),
                ),
                HandoffLog(
                    tenant_id=t,
                    conversation_id=c2.id,
                    motivo="nao_texto",
                    criado_em=h13 + timedelta(minutes=0),
                ),
                LLMCall(
                    tenant_id=t,
                    finalidade="roteador",
                    modelo="m-barato",
                    tokens_entrada=100,
                    tokens_saida=10,
                    custo_usd=Decimal("0.001"),
                    criado_em=h12 + timedelta(minutes=10),
                ),
                LLMCall(
                    tenant_id=t,
                    finalidade="suporte",
                    modelo="m-forte",
                    tokens_entrada=500,
                    tokens_saida=50,
                    custo_usd=Decimal("0.01"),
                    criado_em=h12 + timedelta(minutes=10),
                ),
                LLMCall(
                    tenant_id=t,
                    finalidade="embedding",
                    modelo="m-emb",
                    tokens_entrada=40,
                    tokens_saida=0,
                    custo_usd=Decimal("0.0005"),
                    criado_em=h13 + timedelta(minutes=15),
                ),
                KnowledgeDocument(
                    tenant_id=t, nome_origem="faq.md", content_hash="h", num_trechos=4
                ),
            ]
        )
        await s.commit()


async def popular_b(engine: AsyncEngine, t: uuid.UUID, h12: datetime = H12) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        c = Conversation(
            id=uuid.uuid4(),
            tenant_id=t,
            canal="whatsapp",
            contato_hash="hb",
            contato_enc="eb",
            status="aberta",
            iniciado_em=h12 + timedelta(minutes=1),
        )
        s.add(c)
        await s.flush()
        s.add_all([_m(t, c.id, h12 + timedelta(minutes=2), "lead") for _ in range(4)])
        s.add(
            LLMCall(
                tenant_id=t,
                finalidade="suporte",
                modelo="m-forte",
                tokens_entrada=1,
                tokens_saida=1,
                custo_usd=Decimal("9.5"),
                criado_em=h12 + timedelta(minutes=2),
            )
        )
        await s.commit()


async def linhas(engine: AsyncEngine, t: uuid.UUID) -> dict[datetime, dict[str, Any]]:
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text("SELECT * FROM painel_agregado_hora WHERE tenant_id = :t ORDER BY hora"),
                    {"t": t},
                )
            )
            .mappings()
            .all()
        )
    return {r["hora"]: dict(r) for r in rows}


async def test_agregado_confere_com_a_contagem_direta(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await popular_a(db, tenant_a)
    await popular_b(db, tenant_b)

    horas, _ = await recalcular_empresa(
        tenant_a, H12 - timedelta(hours=1), H13 + timedelta(hours=1)
    )
    assert horas == 2

    r = await linhas(db, tenant_a)
    assert sorted(r) == [H12, H13]
    h12 = r[H12]
    assert (h12["msgs_lead"], h12["msgs_agente"], h12["msgs_humano"]) == (2, 2, 1)
    assert h12["msgs_nao_texto"] == 1
    assert h12["falhas_envio"] == 1
    assert h12["conversas_iniciadas"] == 1
    assert h12["handoffs"] == 2
    assert h12["bloqueios_guardrail"] == 1  # só palavra_gatilho; falha_canal não é guardrail
    assert h12["resp_n"] == 2 and h12["resp_soma_ms"] == 43000
    assert h12["resp_hist"] == [0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0]
    assert h12["intencoes"] == {"agendar": 1}
    assert (h12["tokens_entrada"], h12["tokens_saida"]) == (600, 60)
    assert h12["custo_usd"] == Decimal("0.011000")
    assert h12["custo_roteador"] == Decimal("0.001000") and h12["custo_suporte"] == Decimal(
        "0.010000"
    )
    assert h12["custo_por_modelo"] == {"m-barato": 0.001, "m-forte": 0.01}

    h13 = r[H13]
    assert (h13["msgs_lead"], h13["msgs_agente"]) == (1, 1)
    assert h13["handoffs"] == 1 and h13["bloqueios_guardrail"] == 0
    assert h13["resp_hist"][0] == 1
    assert h13["custo_embedding"] == Decimal("0.000500")

    # A empresa B nunca recebe número da A (e vice-versa).
    await recalcular_empresa(tenant_b, H12, H12)
    rb = await linhas(db, tenant_b)
    assert list(rb) == [H12]
    assert rb[H12]["msgs_lead"] == 4 and rb[H12]["custo_usd"] == Decimal("9.500000")
    assert (await linhas(db, tenant_a))[H12]["msgs_lead"] == 2

    async with db.connect() as conn:
        sit = (
            (
                await conn.execute(
                    text("SELECT * FROM painel_situacao WHERE tenant_id = :t"), {"t": tenant_a}
                )
            )
            .mappings()
            .one()
        )
    assert sit["ultima_mensagem_em"] == H13 + timedelta(minutes=15, seconds=1)
    assert sit["ultimo_remetente"] == "agente"
    assert (sit["conversas_abertas"], sit["conversas_handoff"]) == (1, 1)
    assert (sit["documentos"], sit["trechos"]) == (1, 4)


async def test_recalcular_a_mesma_janela_e_idempotente(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await popular_a(db, tenant_a)
    for _ in range(3):
        await recalcular_empresa(tenant_a, H12, H13)
    r = await linhas(db, tenant_a)
    assert sorted(r) == [H12, H13] and r[H12]["msgs_lead"] == 2

    # Dado corrigido na origem: a janela regravada reflete a correção e não deixa linha velha.
    async with db.begin() as conn:
        await conn.execute(
            text("DELETE FROM messages WHERE tenant_id = :t AND timestamp >= :h"),
            {"t": tenant_a, "h": H13},
        )
        await conn.execute(text("DELETE FROM handoff_log WHERE criado_em >= :h"), {"h": H13})
        await conn.execute(text("DELETE FROM llm_calls WHERE criado_em >= :h"), {"h": H13})
        await conn.execute(text("DELETE FROM conversations WHERE iniciado_em >= :h"), {"h": H13})
    await recalcular_empresa(tenant_a, H12, H13)
    assert sorted(await linhas(db, tenant_a)) == [H12]


async def test_nenhuma_coluna_guarda_texto_nem_contato(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await popular_a(db, tenant_a)
    await recalcular_empresa(tenant_a, H12, H13)
    async with db.connect() as conn:
        dump = (
            await conn.execute(
                text(
                    "SELECT coalesce(string_agg(to_jsonb(a)::text, ' '), '') || "
                    "coalesce((SELECT string_agg(to_jsonb(s)::text, ' ') FROM painel_situacao s), '') "
                    "FROM painel_agregado_hora a"
                )
            )
        ).scalar_one()
    assert "TEXTO-QUE-NAO-PODE-VAZAR" not in dump and "TELEFONE-SECRETO" not in dump


async def test_recalcular_todas_ignora_empresa_com_dados_apagados(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID, tenant_c: uuid.UUID
) -> None:
    await popular_a(db, tenant_a)
    await popular_b(db, tenant_b)
    async with db.begin() as conn:
        await conn.execute(
            text(
                "UPDATE tenants SET status='encerrado', encerrado_em = now(), dados_apagados_em = now() "
                "WHERE id = :t"
            ),
            {"t": tenant_c},
        )
    resultado = await recalcular_todas(agora=H13 + timedelta(hours=1, minutes=30))
    assert resultado.empresas == 2 and resultado.falhas == []
    async with db.connect() as conn:
        ids = {r[0] for r in await conn.execute(text("SELECT tenant_id FROM painel_situacao"))}
    assert ids == {tenant_a, tenant_b}
    assert (await linhas(db, tenant_a)) and (await linhas(db, tenant_b))
