"""Registro de repasse para atendente humano (FR-007, FR-018)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Conversation, HandoffLog


async def registrar_handoff(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    conversation: Conversation,
    message_id: uuid.UUID | None,
    motivo: str,
    confianca: float = 0.0,
) -> HandoffLog:
    """Grava `handoff_log` e marca a conversa como `handoff`. `motivo` segue os códigos do data-model."""
    registro = HandoffLog(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        message_id=message_id,
        motivo=motivo,
        confianca_no_momento=confianca,
    )
    session.add(registro)
    conversation.status = "handoff"
    conversation.agente_atual = "humano"
    conversation.handoff_em = datetime.now(UTC)
    await session.flush()
    return registro
