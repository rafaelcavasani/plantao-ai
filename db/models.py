"""Modelos de dados (SQLAlchemy 2.0).

Ver `specs/001-router-support-agent/data-model.md` e a seção 8.3 de Projeto_Empresa_Autonoma.md.
Todas as tabelas (exceto `tenants`) carregam `tenant_id`, com Row-Level Security no Postgres
(migração 0003). O schema é criado e alterado exclusivamente por Alembic.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

PALAVRAS_GATILHO_PADRAO = ["processo", "procon", "cancelar tudo", "advogado", "reclamação"]
EMBEDDING_DIM = 1536


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    """Uma empresa cliente (ex.: uma clínica odontológica)."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nome_empresa: Mapped[str] = mapped_column(String(255))
    nicho: Mapped[str] = mapped_column(String(100))
    plano: Mapped[str] = mapped_column(String(50), default="recepcionista")
    status: Mapped[str] = mapped_column(
        String(50), default="trial"
    )  # trial|ativo|suspenso|cancelado
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    config: Mapped[TenantConfig] = relationship(back_populates="tenant", uselist=False)


class TenantConfig(Base):
    """Guardrails e preferências de configuração por tenant (ver seção 8.4)."""

    __tablename__ = "tenant_config"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    tom_de_voz: Mapped[str] = mapped_column(Text, default="")
    horario_funcionamento: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    limite_desconto_percentual: Mapped[float] = mapped_column(Float, default=0.0)
    topicos_proibidos: Mapped[list[str]] = mapped_column(JSON, default=list)
    confianca_minima_handoff: Mapped[float] = mapped_column(Float, default=0.7)
    palavras_gatilho: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: list(PALAVRAS_GATILHO_PADRAO)
    )
    router_confidence_threshold: Mapped[float] = mapped_column(Float, default=0.6)
    min_similarity: Mapped[float] = mapped_column(Float, default=0.30)

    tenant: Mapped[Tenant] = relationship(back_populates="config")


class KnowledgeDocument(Base):
    """Documento carregado pelo operador (FAQ, preços, políticas)."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "nome_origem", name="uq_knowledge_documents_tenant_nome"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    nome_origem: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    versao: Mapped[int] = mapped_column(Integer, default=1)
    num_trechos: Mapped[int] = mapped_column(Integer, default=0)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantKnowledge(Base):
    """Trecho de conhecimento (RAG) isolado por tenant."""

    __tablename__ = "tenant_knowledge"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    documento_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    documento_origem: Mapped[str] = mapped_column(String(255))
    chunk_indice: Mapped[int] = mapped_column(Integer, default=0)
    chunk_texto: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Conversation(Base):
    """Uma conversa entre um contato e o conjunto de agentes de um tenant."""

    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "ix_conversations_contato",
            "tenant_id",
            "canal",
            "contato_hash",
            text("ultima_atividade_em DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    canal: Mapped[str] = mapped_column(String(50))  # whatsapp|web|instagram
    contato_hash: Mapped[str] = mapped_column(String(64))  # HMAC-SHA256 do contato (busca)
    contato_enc: Mapped[str] = mapped_column(Text)  # Fernet do contato (envio da resposta)
    status: Mapped[str] = mapped_column(String(50), default="aberta")  # aberta|handoff|resolvida
    agente_atual: Mapped[str] = mapped_column(String(50), default="router")  # router|support|humano
    ultima_atividade_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    handoff_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    iniciado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    messages: Mapped[list[Message]] = relationship(back_populates="conversation")


class Message(Base):
    """Uma mensagem individual dentro de uma conversa."""

    __tablename__ = "messages"
    __table_args__ = (
        Index(
            "uq_messages_tenant_external_id",
            "tenant_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        Index(
            "uq_messages_responde_a",
            "responde_a",
            unique=True,
            postgresql_where=text("responde_a IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    remetente: Mapped[str] = mapped_column(String(20))  # lead|agente|humano
    conteudo: Mapped[str] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(20), default="texto")  # texto|nao_texto
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    intencao: Mapped[str | None] = mapped_column(String(20), nullable=True)
    intencao_confianca: Mapped[float | None] = mapped_column(Float, nullable=True)
    intencoes_secundarias: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    status_envio: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # pendente|enviada|falha
    responde_a: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Lead(Base):
    """Um lead capturado/qualificado pelo Agente SDR (Sprint 5)."""

    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"))
    nome: Mapped[str] = mapped_column(String(255), default="")
    telefone: Mapped[str] = mapped_column(String(50))
    score_qualificacao: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(50), default="novo"
    )  # novo|qualificado|descartado|convertido


class Appointment(Base):
    """Um horário agendado pelo Agente Agendador (Sprint 4)."""

    __tablename__ = "appointments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id"))
    data_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(50), default="confirmado"
    )  # confirmado|remarcado|cancelado|no_show


class BillingEvent(Base):
    """Um evento de cobrança/lembrete gerado pelo Agente de Cobrança (Sprint 6)."""

    __tablename__ = "billing_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(50))  # cobranca|lembrete|renegociacao
    status: Mapped[str] = mapped_column(String(50), default="pendente")
    valor: Mapped[float] = mapped_column(Float, default=0.0)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageMetric(Base):
    """Métricas diárias de uso/custo por tenant (agregadas no Sprint 6)."""

    __tablename__ = "usage_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    data: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    tokens_consumidos: Mapped[int] = mapped_column(Integer, default=0)
    custo_usd: Mapped[float] = mapped_column(Float, default=0.0)
    num_conversas: Mapped[int] = mapped_column(Integer, default=0)
    num_handoffs: Mapped[int] = mapped_column(Integer, default=0)


class HandoffLog(Base):
    """Registro de auditoria de cada repasse para humano."""

    __tablename__ = "handoff_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    motivo: Mapped[str] = mapped_column(Text)
    confianca_no_momento: Mapped[float] = mapped_column(Float, default=0.0)
    resolvido_por_humano: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LLMCall(Base):
    """Uma chamada a modelo de linguagem ou de embedding (FR-017, SC-007)."""

    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    finalidade: Mapped[str] = mapped_column(String(20))  # roteador|suporte|embedding
    modelo: Mapped[str] = mapped_column(String(100))
    tokens_entrada: Mapped[int] = mapped_column(Integer, default=0)
    tokens_saida: Mapped[int] = mapped_column(Integer, default=0)
    custo_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    latencia_ms: Mapped[int] = mapped_column(Integer, default=0)
    sucesso: Mapped[bool] = mapped_column(Boolean, default=True)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
