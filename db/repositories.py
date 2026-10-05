"""Acesso a dados de conversas e mensagens. Toda função recebe uma sessão já ligada ao tenant
(`db.session.tenant_session`), então o RLS do Postgres filtra as linhas."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Conversation, Message, Tenant, TenantConfig

# Chave das travas advisory do estado da empresa (research R-06): a mudança de estado pega a trava
# exclusiva e quem grava uma resposta pega a compartilhada, na mesma chave.
_CHAVE_TRAVA_ESTADO = "hashtextextended('estado_empresa:' || CAST(:t AS text), 0)"


@dataclass(frozen=True)
class Turno:
    remetente: str
    conteudo: str


def agora() -> datetime:
    return datetime.now(UTC)


async def carregar_estado_empresa(session: AsyncSession) -> str | None:
    """`tenants.status` da empresa da sessão (o RLS limita à linha dela); `None` se não enxergar."""
    return (await session.execute(select(Tenant.status))).scalar_one_or_none()


async def travar_estado_compartilhada(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Trava advisory compartilhada até o fim da transação: bloqueia só a mudança de estado."""
    await session.execute(
        text(f"SELECT pg_advisory_xact_lock_shared({_CHAVE_TRAVA_ESTADO})"), {"t": str(tenant_id)}
    )


async def travar_estado_exclusiva(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Trava advisory exclusiva até o fim da transação: espera quem está gravando uma resposta."""
    await session.execute(
        text(f"SELECT pg_advisory_xact_lock({_CHAVE_TRAVA_ESTADO})"), {"t": str(tenant_id)}
    )


async def obter_ou_criar_conversa(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    canal: str,
    contato_hash: str,
    contato_enc: str,
    janela_horas: int = 24,
    recebida_em_suspensao: bool = False,
) -> Conversation:
    """Reutiliza a conversa mais recente do contato com atividade dentro da janela (R-04).

    Com `recebida_em_suspensao`, marca a conversa (nova ou reutilizada) como recebida com a empresa
    suspensa (FR-017). A conversa é sempre iniciada pelo contato nesta entrega.
    """
    limite = agora() - timedelta(hours=janela_horas)
    existente = (
        await session.execute(
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.canal == canal,
                Conversation.contato_hash == contato_hash,
                Conversation.ultima_atividade_em >= limite,
            )
            .order_by(Conversation.ultima_atividade_em.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existente is not None:
        if recebida_em_suspensao and not existente.recebida_em_suspensao:
            existente.recebida_em_suspensao = True
        return existente
    conversa = Conversation(
        tenant_id=tenant_id,
        canal=canal,
        contato_hash=contato_hash,
        contato_enc=contato_enc,
        iniciada_por="contato",
        recebida_em_suspensao=recebida_em_suspensao,
    )
    session.add(conversa)
    await session.flush()
    return conversa


async def inserir_mensagem_lead(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    external_id: str,
    conteudo: str,
    tipo: str,
) -> uuid.UUID | None:
    """Insere a mensagem do lead. Devolve `None` se `(tenant_id, external_id)` já existe (FR-015)."""
    stmt = (
        insert(Message)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            remetente="lead",
            conteudo=conteudo,
            tipo=tipo,
            external_id=external_id,
            timestamp=agora(),
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "external_id"],
            index_where=Message.external_id.is_not(None),
        )
        .returning(Message.id)
    )
    message_id = (await session.execute(stmt)).scalar_one_or_none()
    if message_id is not None:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(ultima_atividade_em=agora())
        )
    return message_id


async def carregar_historico(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    antes_de_message_id: uuid.UUID,
    limite: int = 6,
) -> list[Turno]:
    """Últimas `limite` mensagens anteriores à mensagem atual, da mais antiga para a mais recente."""
    atual = (
        await session.execute(select(Message.timestamp).where(Message.id == antes_de_message_id))
    ).scalar_one()
    linhas = (
        await session.execute(
            select(Message.remetente, Message.conteudo, Message.tipo)
            .where(
                Message.conversation_id == conversation_id,
                Message.timestamp < atual,
                Message.id != antes_de_message_id,
            )
            .order_by(Message.timestamp.desc())
            .limit(limite)
        )
    ).all()
    return [Turno(r.remetente, r.conteudo) for r in reversed(linhas) if r.tipo == "texto"]


async def resposta_existente(session: AsyncSession, message_id: uuid.UUID) -> Message | None:
    return (
        await session.execute(select(Message).where(Message.responde_a == message_id))
    ).scalar_one_or_none()


async def carregar_config(session: AsyncSession, tenant_id: uuid.UUID) -> TenantConfig:
    return (
        await session.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
    ).scalar_one()


async def ultima_atividade_humana(
    session: AsyncSession, conversation_id: uuid.UUID
) -> datetime | None:
    return (
        await session.execute(
            select(Message.timestamp)
            .where(Message.conversation_id == conversation_id, Message.remetente == "humano")
            .order_by(Message.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
