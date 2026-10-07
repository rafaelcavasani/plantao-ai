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
    BigInteger,
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from db.config_padrao import CONFIG_PADRAO, PALAVRAS_GATILHO_PADRAO

__all__ = ["PALAVRAS_GATILHO_PADRAO"]

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
    slug: Mapped[str] = mapped_column(String(63), unique=True)  # chave natural do onboarding
    status: Mapped[str] = mapped_column(
        String(50), default="em_configuracao"
    )  # em_configuracao|ativo|suspenso|encerrado
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ativado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    encerrado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dados_apagados_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    versao: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1"
    )  # concorrência otimista do painel (spec 004, FR-040)
    config: Mapped[TenantConfig] = relationship(back_populates="tenant", uselist=False)


class TenantConfig(Base):
    """Guardrails e preferências de configuração por tenant (ver seção 8.4)."""

    __tablename__ = "tenant_config"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    tom_de_voz: Mapped[str] = mapped_column(Text, default=lambda: CONFIG_PADRAO["tom_de_voz"])
    horario_funcionamento: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    limite_desconto_percentual: Mapped[float] = mapped_column(
        Float, default=CONFIG_PADRAO["limite_desconto_percentual"]
    )
    topicos_proibidos: Mapped[list[str]] = mapped_column(JSON, default=list)
    confianca_minima_handoff: Mapped[float] = mapped_column(
        Float, default=CONFIG_PADRAO["confianca_minima_handoff"]
    )
    palavras_gatilho: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: list(PALAVRAS_GATILHO_PADRAO)
    )
    router_confidence_threshold: Mapped[float] = mapped_column(
        Float, default=CONFIG_PADRAO["router_confidence_threshold"]
    )
    min_similarity: Mapped[float] = mapped_column(Float, default=CONFIG_PADRAO["min_similarity"])
    handoff_ttl_minutos: Mapped[int] = mapped_column(
        Integer, default=CONFIG_PADRAO["handoff_ttl_minutos"]
    )
    limite_mensagens_por_minuto: Mapped[int] = mapped_column(
        Integer, default=CONFIG_PADRAO["limite_mensagens_por_minuto"]
    )

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
    iniciada_por: Mapped[str] = mapped_column(String(20), default="contato")  # contato|empresa
    recebida_em_suspensao: Mapped[bool] = mapped_column(Boolean, default=False)

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


class ChannelConnection(Base):
    """Diretório de roteamento: qual empresa é dona de qual instância do canal.

    Exceção declarada ao princípio III: leitura aberta (o webhook precisa localizar a empresa antes
    de saber qual ela é); escrita restrita à empresa dona. Sem colunas sensíveis.
    """

    __tablename__ = "channel_connections"
    __table_args__ = (
        UniqueConstraint("instance_name", name="uq_channel_connections_instance"),
        UniqueConstraint("tenant_id", "canal", name="uq_channel_connections_tenant_canal"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    canal: Mapped[str] = mapped_column(String(50))  # whatsapp
    provedor: Mapped[str] = mapped_column(String(30))  # evolution
    instance_name: Mapped[str] = mapped_column(String(100))
    verificada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChannelCredential(Base):
    """Segredos da conexão: hash do segredo de entrega e chave de envio cifrada."""

    __tablename__ = "channel_credentials"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel_connections.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    webhook_secret_hash: Mapped[str] = mapped_column(String(64))  # sha256 do segredo
    api_key_enc: Mapped[str] = mapped_column(Text)  # Fernet da chave de envio
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReadinessCheck(Base):
    """Resultado de uma verificação de prontidão ou de uma conversa de teste."""

    __tablename__ = "readiness_checks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    executado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    operador: Mapped[str] = mapped_column(String(100))
    tipo: Mapped[str] = mapped_column(String(20))  # prontidao|conversa_teste
    config_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    documentos_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    conexao_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    conversa_teste_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    aprovado: Mapped[bool] = mapped_column(Boolean, default=False)
    detalhes: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    """Trilha de auditoria só de inclusão. Sem FK para `tenants`: sobrevive à exclusão de dados."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_tenant_criado", "tenant_id", text("criado_em DESC")),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    entidade: Mapped[str] = mapped_column(String(20))  # config|estado|conexao|dados
    campo: Mapped[str] = mapped_column(String(100))
    valor_anterior: Mapped[object | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    valor_novo: Mapped[object | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    operador: Mapped[str] = mapped_column(String(100))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PainelAgregadoHora(Base):
    """Agregado por empresa e hora (UTC) que alimenta o painel de operação (spec 004, ADR-0008).

    Escrito só pelo job `agregar_painel`, sob `tenant_session`. Não guarda texto, contato nem identificador de
    conversa. Chave primária `(tenant_id, hora)`.
    """

    __tablename__ = "painel_agregado_hora"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, index=True)
    msgs_lead: Mapped[int] = mapped_column(Integer, default=0)
    msgs_agente: Mapped[int] = mapped_column(Integer, default=0)
    msgs_humano: Mapped[int] = mapped_column(Integer, default=0)
    msgs_nao_texto: Mapped[int] = mapped_column(Integer, default=0)
    conversas_iniciadas: Mapped[int] = mapped_column(Integer, default=0)
    handoffs: Mapped[int] = mapped_column(Integer, default=0)
    handoffs_resolvidos: Mapped[int] = mapped_column(Integer, default=0)
    bloqueios_guardrail: Mapped[int] = mapped_column(Integer, default=0)
    falhas_envio: Mapped[int] = mapped_column(Integer, default=0)
    resp_n: Mapped[int] = mapped_column(Integer, default=0)
    resp_soma_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    resp_hist: Mapped[list[int]] = mapped_column(JSONB, default=list)
    intencoes: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    tokens_entrada: Mapped[int] = mapped_column(BigInteger, default=0)
    tokens_saida: Mapped[int] = mapped_column(BigInteger, default=0)
    custo_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal(0))
    custo_roteador: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal(0))
    custo_suporte: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal(0))
    custo_embedding: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal(0))
    custo_por_modelo: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PainelSituacao(Base):
    """Situação corrente de cada empresa para o painel (uma linha por empresa; spec 004, ADR-0008)."""

    __tablename__ = "painel_situacao"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    ultima_mensagem_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ultimo_remetente: Mapped[str | None] = mapped_column(String(20), nullable=True)
    conversas_abertas: Mapped[int] = mapped_column(Integer, default=0)
    conversas_handoff: Mapped[int] = mapped_column(Integer, default=0)
    documentos: Mapped[int] = mapped_column(Integer, default=0)
    trechos: Mapped[int] = mapped_column(Integer, default=0)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
