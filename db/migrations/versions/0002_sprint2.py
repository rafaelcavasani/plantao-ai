"""sprint 2: roteador + suporte com base de conhecimento

Alterações descritas em specs/001-router-support-agent/data-model.md.

ATENÇÃO (dados): as conversas do Sprint 1 guardam o telefone em texto puro (`contato_id`) e não podem
ser convertidas em `contato_hash`/`contato_enc` sem a chave de PII. Esta migração APAGA `handoff_log`,
`messages`, `conversations` e `tenant_knowledge` existentes. Eram dados de teste do eco do Sprint 1.
O `downgrade` recria a estrutura antiga, sem os dados.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
GATILHOS_PADRAO = '["processo","procon","cancelar tudo","advogado","reclamação"]'


def upgrade() -> None:
    # tenant_config
    op.add_column(
        "tenant_config",
        sa.Column(
            "palavras_gatilho",
            sa.JSON,
            nullable=False,
            server_default=sa.text(f"'{GATILHOS_PADRAO}'::json"),
        ),
    )
    op.add_column(
        "tenant_config",
        sa.Column("router_confidence_threshold", sa.Float, nullable=False, server_default="0.6"),
    )
    op.add_column(
        "tenant_config", sa.Column("min_similarity", sa.Float, nullable=False, server_default="0.3")
    )

    # dados legados (ver docstring)
    op.execute("DELETE FROM handoff_log")
    op.execute("DELETE FROM messages")
    op.execute("DELETE FROM conversations")
    op.execute("DELETE FROM tenant_knowledge")

    # conversations
    op.drop_column("conversations", "contato_id")
    op.add_column("conversations", sa.Column("contato_hash", sa.String(64), nullable=False))
    op.add_column("conversations", sa.Column("contato_enc", sa.Text, nullable=False))
    op.add_column(
        "conversations",
        sa.Column(
            "ultima_atividade_em",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "conversations", sa.Column("handoff_em", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_conversations_contato",
        "conversations",
        ["tenant_id", "canal", "contato_hash", sa.text("ultima_atividade_em DESC")],
    )

    # messages
    op.add_column(
        "messages", sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False)
    )
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"])
    op.add_column(
        "messages", sa.Column("tipo", sa.String(20), nullable=False, server_default="texto")
    )
    op.add_column("messages", sa.Column("external_id", sa.String(128), nullable=True))
    op.add_column("messages", sa.Column("intencao", sa.String(20), nullable=True))
    op.add_column("messages", sa.Column("intencao_confianca", sa.Float, nullable=True))
    op.add_column("messages", sa.Column("intencoes_secundarias", sa.JSON, nullable=True))
    op.add_column("messages", sa.Column("status_envio", sa.String(20), nullable=True))
    op.add_column(
        "messages", sa.Column("responde_a", UUID, sa.ForeignKey("messages.id"), nullable=True)
    )
    op.create_index(
        "uq_messages_tenant_external_id",
        "messages",
        ["tenant_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_index(
        "uq_messages_responde_a",
        "messages",
        ["responde_a"],
        unique=True,
        postgresql_where=sa.text("responde_a IS NOT NULL"),
    )

    # handoff_log
    op.add_column(
        "handoff_log", sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False)
    )
    op.create_index("ix_handoff_log_tenant_id", "handoff_log", ["tenant_id"])
    op.add_column(
        "handoff_log", sa.Column("message_id", UUID, sa.ForeignKey("messages.id"), nullable=True)
    )

    # knowledge_documents e tenant_knowledge
    op.create_table(
        "knowledge_documents",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("nome_origem", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("versao", sa.Integer, nullable=False, server_default="1"),
        sa.Column("num_trechos", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "nome_origem", name="uq_knowledge_documents_tenant_nome"),
    )
    op.create_index("ix_knowledge_documents_tenant_id", "knowledge_documents", ["tenant_id"])
    op.add_column(
        "tenant_knowledge",
        sa.Column(
            "documento_id",
            UUID,
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.create_index("ix_tenant_knowledge_documento_id", "tenant_knowledge", ["documento_id"])
    op.add_column(
        "tenant_knowledge",
        sa.Column("chunk_indice", sa.Integer, nullable=False, server_default="0"),
    )

    # llm_calls
    op.create_table(
        "llm_calls",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("conversation_id", UUID, sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("message_id", UUID, sa.ForeignKey("messages.id"), nullable=True),
        sa.Column("finalidade", sa.String(20), nullable=False),
        sa.Column("modelo", sa.String(100), nullable=False),
        sa.Column("tokens_entrada", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_saida", sa.Integer, nullable=False, server_default="0"),
        sa.Column("custo_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("latencia_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sucesso", sa.Boolean, nullable=False),
        sa.Column("erro", sa.Text, nullable=True),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_llm_calls_tenant_id", "llm_calls", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("llm_calls")

    op.drop_column("tenant_knowledge", "chunk_indice")
    op.drop_index("ix_tenant_knowledge_documento_id", table_name="tenant_knowledge")
    op.execute("DELETE FROM tenant_knowledge")
    op.drop_column("tenant_knowledge", "documento_id")
    op.drop_table("knowledge_documents")

    op.drop_column("handoff_log", "message_id")
    op.drop_index("ix_handoff_log_tenant_id", table_name="handoff_log")
    op.drop_column("handoff_log", "tenant_id")

    op.drop_index("uq_messages_responde_a", table_name="messages")
    op.drop_index("uq_messages_tenant_external_id", table_name="messages")
    for coluna in (
        "responde_a",
        "status_envio",
        "intencoes_secundarias",
        "intencao_confianca",
        "intencao",
        "external_id",
        "tipo",
    ):
        op.drop_column("messages", coluna)
    op.drop_index("ix_messages_tenant_id", table_name="messages")
    op.drop_column("messages", "tenant_id")

    op.drop_index("ix_conversations_contato", table_name="conversations")
    op.drop_column("conversations", "handoff_em")
    op.drop_column("conversations", "ultima_atividade_em")
    op.drop_column("conversations", "contato_enc")
    op.drop_column("conversations", "contato_hash")
    op.add_column(
        "conversations", sa.Column("contato_id", sa.String(100), nullable=False, server_default="")
    )
    op.alter_column("conversations", "contato_id", server_default=None)

    op.drop_column("tenant_config", "min_similarity")
    op.drop_column("tenant_config", "router_confidence_threshold")
    op.drop_column("tenant_config", "palavras_gatilho")
