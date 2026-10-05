"""Isolamento entre tenants com RLS e o papel `plantao_app` (T022, princípio III, FR-021)."""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from db.models import (
    Conversation,
    HandoffLog,
    KnowledgeDocument,
    LLMCall,
    Message,
    Tenant,
    TenantConfig,
    TenantKnowledge,
)
from db.session import get_session_factory, tenant_session

pytestmark = pytest.mark.integration

TABELAS = [
    Conversation,
    Message,
    KnowledgeDocument,
    TenantKnowledge,
    LLMCall,
    HandoffLog,
    TenantConfig,
]


async def _popular(engine: AsyncEngine, tenant_id: uuid.UUID) -> None:
    async with AsyncSession(engine) as s:
        conv = Conversation(
            tenant_id=tenant_id, canal="whatsapp", contato_hash="h", contato_enc="e"
        )
        s.add(conv)
        await s.flush()
        msg = Message(
            tenant_id=tenant_id,
            conversation_id=conv.id,
            remetente="lead",
            conteudo="oi",
            external_id="x1",
        )
        doc = KnowledgeDocument(
            tenant_id=tenant_id, nome_origem="faq.md", content_hash="c", num_trechos=1
        )
        s.add_all([msg, doc])
        await s.flush()
        s.add_all(
            [
                TenantKnowledge(
                    tenant_id=tenant_id,
                    documento_id=doc.id,
                    documento_origem="faq.md",
                    chunk_texto="t",
                    embedding=[0.1] * 1536,
                ),
                LLMCall(tenant_id=tenant_id, finalidade="roteador", modelo="m", sucesso=True),
                HandoffLog(
                    tenant_id=tenant_id, conversation_id=conv.id, message_id=msg.id, motivo="x"
                ),
            ]
        )
        await s.commit()


async def _contar(session: AsyncSession, modelo: type) -> int:
    return len((await session.execute(select(modelo))).scalars().all())


async def test_papel_da_aplicacao_nao_e_superusuario(db: AsyncEngine) -> None:
    async with get_session_factory()() as s:
        row = (
            await s.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
    assert row == (False, False)


async def test_tenant_b_nao_le_dados_do_tenant_a(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await _popular(db, tenant_a)

    async with tenant_session(tenant_a) as s:
        for modelo in TABELAS:
            assert await _contar(s, modelo) == 1, modelo.__name__

    async with tenant_session(tenant_b) as s:
        for modelo in [m for m in TABELAS if m is not TenantConfig]:
            assert await _contar(s, modelo) == 0, modelo.__name__
        tenants = (await s.execute(select(Tenant.id))).scalars().all()
        assert tenants == [tenant_b]


async def test_sem_tenant_definido_retorna_zero_linhas(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _popular(db, tenant_a)
    async with get_session_factory()() as s:
        for modelo in [*TABELAS, Tenant]:
            assert await _contar(s, modelo) == 0, modelo.__name__


async def test_tenant_nao_grava_para_outro_tenant(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_a) as s:
            s.add(
                Conversation(
                    tenant_id=tenant_b, canal="whatsapp", contato_hash="h", contato_enc="e"
                )
            )
            await s.flush()


async def test_busca_vetorial_respeita_tenant(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await _popular(db, tenant_a)
    async with tenant_session(tenant_b) as s:
        distancia = TenantKnowledge.embedding.cosine_distance([0.1] * 1536)
        rows = (await s.execute(select(TenantKnowledge.id).order_by(distancia).limit(4))).all()
    assert rows == []
