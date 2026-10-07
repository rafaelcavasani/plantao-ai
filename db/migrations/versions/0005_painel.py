"""painel de operação: papel plantao_painel, agregados por hora e situação por empresa (spec 004)

- `tenants.versao`: concorrência otimista das edições feitas pelo painel (FR-040).
- `painel_agregado_hora` e `painel_situacao`: tabelas mantidas pelo job `agregar_painel` sob RLS (ADR-0008).
- Papel `plantao_painel`: só `SELECT`, com privilégio por coluna. Nunca lê `messages.conteudo`,
  `messages.external_id`, `conversations.contato_*`, `tenant_knowledge.chunk_texto` nem credenciais (ADR-0006).

A senha do papel vem de `PAINEL_DB_PASSWORD` (padrão de desenvolvimento: `plantao_painel`). Em produção,
defina um valor próprio antes de rodar esta migração.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from core.config import settings

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP = "plantao_app"
PAINEL = "plantao_painel"
_TENANT_ATUAL = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
UUID = postgresql.UUID(as_uuid=True)

TABELAS_NOVAS = ("painel_agregado_hora", "painel_situacao")

# Tabelas lidas pelo painel com todas as colunas. As tabelas de conteúdo ficam com lista explícita de colunas
# (abaixo): o que não está na lista o papel simplesmente não consegue ler.
LEITURA_TOTAL = (
    "tenants",
    "tenant_config",
    "readiness_checks",
    "audit_log",
    "handoff_log",
    "painel_agregado_hora",
    "painel_situacao",
)
LEITURA_POR_COLUNA = {
    "channel_connections": "id, tenant_id, canal, provedor, instance_name, verificada_em, criado_em",
    "knowledge_documents": "id, tenant_id, nome_origem, versao, num_trechos, atualizado_em",
    "conversations": (
        "id, tenant_id, canal, status, agente_atual, ultima_atividade_em, handoff_em, iniciado_em, "
        "iniciada_por, recebida_em_suspensao"
    ),
    "messages": (
        "id, tenant_id, conversation_id, remetente, tipo, intencao, intencao_confianca, "
        "status_envio, timestamp, responde_a"
    ),
}
# `channel_connections` já tem leitura aberta (política `roteamento_leitura`); as demais precisam da política.
COM_POLITICA_DO_PAINEL = (*LEITURA_TOTAL, "knowledge_documents", "conversations", "messages")
CONTADORES = (
    "msgs_lead",
    "msgs_agente",
    "msgs_humano",
    "msgs_nao_texto",
    "conversas_iniciadas",
    "handoffs",
    "handoffs_resolvidos",
    "bloqueios_guardrail",
    "falhas_envio",
    "resp_n",
)
CUSTOS = ("custo_usd", "custo_roteador", "custo_suporte", "custo_embedding")


def _atualizado_em() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "atualizado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.add_column("tenants", sa.Column("versao", sa.Integer(), nullable=False, server_default="1"))

    op.create_table(
        "painel_agregado_hora",
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("hora", sa.DateTime(timezone=True), nullable=False),
        *[sa.Column(c, sa.Integer(), nullable=False, server_default="0") for c in CONTADORES],
        sa.Column("resp_soma_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("resp_hist", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("intencoes", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("tokens_entrada", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("tokens_saida", sa.BigInteger(), nullable=False, server_default="0"),
        *[sa.Column(c, sa.Numeric(14, 6), nullable=False, server_default="0") for c in CUSTOS],
        sa.Column("custo_por_modelo", postgresql.JSONB(), nullable=False, server_default="{}"),
        _atualizado_em(),
        sa.PrimaryKeyConstraint("tenant_id", "hora"),
    )
    op.create_index("ix_painel_agregado_hora_hora", "painel_agregado_hora", ["hora"])
    op.create_table(
        "painel_situacao",
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("ultima_mensagem_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_remetente", sa.String(20), nullable=True),
        *[
            sa.Column(c, sa.Integer(), nullable=False, server_default="0")
            for c in ("conversas_abertas", "conversas_handoff", "documentos", "trechos")
        ],
        _atualizado_em(),
        sa.PrimaryKeyConstraint("tenant_id"),
    )

    senha = settings.painel_db_password.replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{PAINEL}') THEN
                CREATE ROLE {PAINEL} LOGIN PASSWORD '{senha}' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {PAINEL}")

    for tabela in TABELAS_NOVAS:
        op.execute(f"ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tabela} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {tabela} "
            f"USING (tenant_id = {_TENANT_ATUAL}) WITH CHECK (tenant_id = {_TENANT_ATUAL})"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tabela} TO {APP}")

    for tabela in LEITURA_TOTAL:
        op.execute(f"GRANT SELECT ON {tabela} TO {PAINEL}")
    for tabela, colunas in LEITURA_POR_COLUNA.items():
        op.execute(f"GRANT SELECT ({colunas}) ON {tabela} TO {PAINEL}")
    for tabela in COM_POLITICA_DO_PAINEL:
        op.execute(f"CREATE POLICY painel_leitura ON {tabela} FOR SELECT TO {PAINEL} USING (true)")


def downgrade() -> None:
    for tabela in COM_POLITICA_DO_PAINEL:
        if tabela not in TABELAS_NOVAS:
            op.execute(f"DROP POLICY IF EXISTS painel_leitura ON {tabela}")
    for tabela in reversed(TABELAS_NOVAS):
        op.drop_table(tabela)  # leva junto políticas, índices e privilégios
    op.drop_column("tenants", "versao")
    op.execute(f"DROP OWNED BY {PAINEL}")
    # O papel é do cluster: só some se nenhum outro banco ainda depender dele.
    op.execute(
        f"""
        DO $$
        BEGIN
            DROP ROLE IF EXISTS {PAINEL};
        EXCEPTION WHEN dependent_objects_still_exist THEN
            NULL;
        END
        $$;
        """
    )
