"""baseline: schema do Sprint 1

Reproduz o schema criado por `scripts/init_db.py` no Sprint 1, para que as migrações seguintes
possam alterá-lo de forma versionada.

Banco de desenvolvimento que já tem essas tabelas (criadas por `create_all`): rode
`alembic stamp 0001` em vez de `upgrade` para este passo.

Revision ID: 0001
Revises:
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def _criado_em(nome: str = "criado_em") -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(nome, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "tenants",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("nome_empresa", sa.String(255), nullable=False),
        sa.Column("nicho", sa.String(100), nullable=False),
        sa.Column("plano", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        _criado_em(),
    )
    op.create_table(
        "tenant_config",
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("tom_de_voz", sa.Text, nullable=False),
        sa.Column("horario_funcionamento", sa.JSON, nullable=False),
        sa.Column("limite_desconto_percentual", sa.Float, nullable=False),
        sa.Column("topicos_proibidos", sa.JSON, nullable=False),
        sa.Column("confianca_minima_handoff", sa.Float, nullable=False),
    )
    op.create_table(
        "tenant_knowledge",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("documento_origem", sa.String(255), nullable=False),
        sa.Column("chunk_texto", sa.Text, nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        _criado_em(),
    )
    op.create_index("ix_tenant_knowledge_tenant_id", "tenant_knowledge", ["tenant_id"])
    op.create_table(
        "conversations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("canal", sa.String(50), nullable=False),
        sa.Column("contato_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("agente_atual", sa.String(50), nullable=False),
        _criado_em("iniciado_em"),
    )
    op.create_index("ix_conversations_tenant_id", "conversations", ["tenant_id"])
    op.create_table(
        "messages",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("conversation_id", UUID, sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("remetente", sa.String(20), nullable=False),
        sa.Column("conteudo", sa.Text, nullable=False),
        _criado_em("timestamp"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_table(
        "leads",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("conversation_id", UUID, sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("nome", sa.String(255), nullable=False),
        sa.Column("telefone", sa.String(50), nullable=False),
        sa.Column("score_qualificacao", sa.Integer, nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
    )
    op.create_index("ix_leads_tenant_id", "leads", ["tenant_id"])
    op.create_table(
        "appointments",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("lead_id", UUID, sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("data_hora", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
    )
    op.create_index("ix_appointments_tenant_id", "appointments", ["tenant_id"])
    op.create_table(
        "billing_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("tipo", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("valor", sa.Float, nullable=False),
        _criado_em(),
    )
    op.create_index("ix_billing_events_tenant_id", "billing_events", ["tenant_id"])
    op.create_table(
        "usage_metrics",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("data", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("tokens_consumidos", sa.Integer, nullable=False),
        sa.Column("custo_usd", sa.Float, nullable=False),
        sa.Column("num_conversas", sa.Integer, nullable=False),
        sa.Column("num_handoffs", sa.Integer, nullable=False),
    )
    op.create_index("ix_usage_metrics_tenant_id", "usage_metrics", ["tenant_id"])
    op.create_table(
        "handoff_log",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("conversation_id", UUID, sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("motivo", sa.Text, nullable=False),
        sa.Column("confianca_no_momento", sa.Float, nullable=False),
        sa.Column("resolvido_por_humano", sa.Boolean, nullable=False),
        _criado_em(),
    )
    op.create_index("ix_handoff_log_conversation_id", "handoff_log", ["conversation_id"])


def downgrade() -> None:
    for tabela in (
        "handoff_log",
        "usage_metrics",
        "billing_events",
        "appointments",
        "leads",
        "messages",
        "conversations",
        "tenant_knowledge",
        "tenant_config",
        "tenants",
    ):
        op.drop_table(tabela)
