"""Auxiliares dos testes de integração do pipeline (worker + banco real)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agents.orchestrator.graph import Grafo
from core.security.crypto import get_cripto
from db.models import Message
from db.repositories import inserir_mensagem_lead, obter_ou_criar_conversa
from db.session import tenant_session
from tests.fakes.channel import FakeChannel
from tests.fakes.llm import FakeLLMClient

JID = "5511999990000@s.whatsapp.net"


async def receber(
    tenant_id: uuid.UUID,
    texto: str = "Qual o horário de atendimento aos sábados?",
    *,
    tipo: str = "texto",
    contato: str = JID,
    external_id: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Simula o que o webhook faz: conversa + mensagem do lead. Devolve (message_id, conversation_id)."""
    cripto = get_cripto()
    async with tenant_session(tenant_id) as s:
        conversa = await obter_ou_criar_conversa(
            s,
            tenant_id=tenant_id,
            canal="whatsapp",
            contato_hash=cripto.hash_contato(contato),
            contato_enc=cripto.encrypt(contato),
        )
        message_id = await inserir_mensagem_lead(
            s,
            tenant_id=tenant_id,
            conversation_id=conversa.id,
            external_id=external_id or uuid.uuid4().hex,
            conteudo=texto,
            tipo=tipo,
        )
    assert message_id is not None
    return message_id, conversa.id


async def mensagem_humana(
    db: AsyncEngine, tenant_id: uuid.UUID, conversation_id: uuid.UUID, minutos_atras: int
) -> None:
    async with AsyncSession(db) as s:
        s.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                remetente="humano",
                conteudo="Já te respondo!",
                timestamp=datetime.now(UTC) - timedelta(minutes=minutos_atras),
            )
        )
        await s.commit()


async def marcar_handoff(db: AsyncEngine, conversation_id: uuid.UUID, minutos_atras: int) -> None:
    async with db.begin() as conn:
        await conn.execute(
            text(
                "UPDATE conversations SET status='handoff', agente_atual='humano', handoff_em=:t WHERE id=:c"
            ),
            {"t": datetime.now(UTC) - timedelta(minutes=minutos_atras), "c": conversation_id},
        )


async def consultar(db: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with db.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


def contexto(llm: FakeLLMClient, channel: FakeChannel | None = None) -> dict[str, Any]:
    return {"grafo": Grafo(llm), "channel": channel or FakeChannel()}
