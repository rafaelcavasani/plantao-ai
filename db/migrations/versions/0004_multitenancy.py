"""multi-tenancy real: slug, ciclo de vida, conexões de canal, credenciais, prontidão e auditoria

- `tenants`: `slug` único, estados `em_configuracao|ativo|suspenso|encerrado` (CHECK) e carimbos de ciclo
  de vida. `trial` vira `em_configuracao` e `cancelado` vira `encerrado`; o `downgrade` reverte.
- `tenant_config`: `handoff_ttl_minutos` e `limite_mensagens_por_minuto`, com CHECKs de faixa.
- `conversations`: `iniciada_por` e `recebida_em_suspensao`.
- Novas tabelas com RLS forçado: `channel_connections` (leitura aberta para roteamento, escrita por
  empresa), `channel_credentials`, `readiness_checks` e `audit_log` (só `SELECT` e `INSERT`; sem FK).

Dados de empresas existentes (piloto) não são alterados além do `slug` e do mapeamento de `status`.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05
"""

import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "plantao_app"
UUID = postgresql.UUID(as_uuid=True)
_TENANT_ATUAL = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
TABELAS_NOVAS = ("channel_connections", "channel_credentials", "readiness_checks", "audit_log")
ESTADOS = "('em_configuracao', 'ativo', 'suspenso', 'encerrado')"

CHECKS_CONFIG = {
    "ck_tenant_config_confianca_minima_handoff": ("confianca_minima_handoff BETWEEN 0 AND 1"),
    "ck_tenant_config_router_confidence_threshold": ("router_confidence_threshold BETWEEN 0 AND 1"),
    "ck_tenant_config_min_similarity": "min_similarity BETWEEN 0 AND 1",
    "ck_tenant_config_limite_desconto": "limite_desconto_percentual BETWEEN 0 AND 100",
    "ck_tenant_config_handoff_ttl": "handoff_ttl_minutos BETWEEN 1 AND 1440",
    "ck_tenant_config_limite_mensagens": "limite_mensagens_por_minuto BETWEEN 1 AND 6000",
}


def _slug(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")
    return (base or "empresa")[:50].strip("-") or "empresa"


def _preencher_slugs() -> None:
    conn = op.get_bind()
    linhas = conn.execute(
        sa.text("SELECT id, nome_empresa FROM tenants ORDER BY criado_em, id")
    ).fetchall()
    usados: set[str] = set()
    for tenant_id, nome in linhas:
        slug = _slug(nome)
        if slug in usados:
            slug = f"{slug}-{str(tenant_id).replace('-', '')[:8]}"
        usados.add(slug)
        conn.execute(
            sa.text("UPDATE tenants SET slug = :s WHERE id = :i"), {"s": slug, "i": tenant_id}
        )


def _criado_em() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    # --- tenants -------------------------------------------------------------------------------
    op.add_column("tenants", sa.Column("slug", sa.String(63), nullable=True))
    op.add_column("tenants", sa.Column("ativado_em", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenants", sa.Column("encerrado_em", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "tenants", sa.Column("dados_apagados_em", sa.DateTime(timezone=True), nullable=True)
    )

    # `tenants` tem RLS forçado desde a 0003; sem isso o dono não enxergaria as linhas aqui.
    op.execute("ALTER TABLE tenants NO FORCE ROW LEVEL SECURITY")
    _preencher_slugs()
    op.execute("UPDATE tenants SET status = 'encerrado' WHERE status = 'cancelado'")
    op.execute(f"UPDATE tenants SET status = 'em_configuracao' WHERE status NOT IN {ESTADOS}")
    op.execute("UPDATE tenants SET ativado_em = criado_em WHERE status IN ('ativo', 'suspenso')")
    op.execute("UPDATE tenants SET encerrado_em = now() WHERE status = 'encerrado'")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")

    op.alter_column("tenants", "slug", nullable=False)
    op.create_unique_constraint("uq_tenants_slug", "tenants", ["slug"])
    op.create_check_constraint(
        "ck_tenants_slug_formato", "tenants", "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'"
    )
    op.create_check_constraint("ck_tenants_status", "tenants", f"status IN {ESTADOS}")

    # --- tenant_config -------------------------------------------------------------------------
    op.add_column(
        "tenant_config",
        sa.Column("handoff_ttl_minutos", sa.Integer, nullable=False, server_default="60"),
    )
    op.add_column(
        "tenant_config",
        sa.Column("limite_mensagens_por_minuto", sa.Integer, nullable=False, server_default="60"),
    )
    for nome, regra in CHECKS_CONFIG.items():
        op.create_check_constraint(nome, "tenant_config", regra)

    # --- conversations -------------------------------------------------------------------------
    op.add_column(
        "conversations",
        sa.Column("iniciada_por", sa.String(20), nullable=False, server_default="contato"),
    )
    op.add_column(
        "conversations",
        sa.Column("recebida_em_suspensao", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "ck_conversations_iniciada_por", "conversations", "iniciada_por IN ('contato', 'empresa')"
    )

    # --- tabelas novas -------------------------------------------------------------------------
    op.create_table(
        "channel_connections",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("canal", sa.String(50), nullable=False),
        sa.Column("provedor", sa.String(30), nullable=False),
        sa.Column("instance_name", sa.String(100), nullable=False),
        sa.Column("verificada_em", sa.DateTime(timezone=True), nullable=True),
        _criado_em(),
        sa.UniqueConstraint("instance_name", name="uq_channel_connections_instance"),
        sa.UniqueConstraint("tenant_id", "canal", name="uq_channel_connections_tenant_canal"),
    )
    op.create_index("ix_channel_connections_tenant_id", "channel_connections", ["tenant_id"])

    op.create_table(
        "channel_credentials",
        sa.Column(
            "connection_id",
            UUID,
            sa.ForeignKey("channel_connections.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("webhook_secret_hash", sa.String(64), nullable=False),
        sa.Column("api_key_enc", sa.Text, nullable=False),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_channel_credentials_tenant_id", "channel_credentials", ["tenant_id"])

    op.create_table(
        "readiness_checks",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "executado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("operador", sa.String(100), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("config_ok", sa.Boolean, nullable=True),
        sa.Column("documentos_ok", sa.Boolean, nullable=True),
        sa.Column("conexao_ok", sa.Boolean, nullable=True),
        sa.Column("conversa_teste_ok", sa.Boolean, nullable=True),
        sa.Column("aprovado", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("detalhes", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.CheckConstraint("tipo IN ('prontidao', 'conversa_teste')", name="ck_readiness_tipo"),
    )
    op.create_index("ix_readiness_checks_tenant_id", "readiness_checks", ["tenant_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),  # sem FK: sobrevive à exclusão de dados
        sa.Column("entidade", sa.String(20), nullable=False),
        sa.Column("campo", sa.String(100), nullable=False),
        sa.Column("valor_anterior", sa.JSON, nullable=True),
        sa.Column("valor_novo", sa.JSON, nullable=True),
        sa.Column("operador", sa.String(100), nullable=False),
        _criado_em(),
        sa.CheckConstraint(
            "entidade IN ('config', 'estado', 'conexao', 'dados')", name="ck_audit_log_entidade"
        ),
    )
    op.create_index(
        "ix_audit_log_tenant_criado", "audit_log", ["tenant_id", sa.text("criado_em DESC")]
    )

    # --- RLS e privilégios ---------------------------------------------------------------------
    for tabela in TABELAS_NOVAS:
        op.execute(f"ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tabela} FORCE ROW LEVEL SECURITY")

    for tabela in ("channel_credentials", "readiness_checks", "audit_log"):
        op.execute(
            f"CREATE POLICY tenant_isolation ON {tabela} "
            f"USING (tenant_id = {_TENANT_ATUAL}) WITH CHECK (tenant_id = {_TENANT_ATUAL})"
        )

    # Diretório de roteamento: leitura aberta (o webhook precisa achar a empresa), escrita por empresa.
    op.execute("CREATE POLICY roteamento_leitura ON channel_connections FOR SELECT USING (true)")
    op.execute(
        "CREATE POLICY tenant_insert ON channel_connections FOR INSERT "
        f"WITH CHECK (tenant_id = {_TENANT_ATUAL})"
    )
    op.execute(
        "CREATE POLICY tenant_update ON channel_connections FOR UPDATE "
        f"USING (tenant_id = {_TENANT_ATUAL}) WITH CHECK (tenant_id = {_TENANT_ATUAL})"
    )
    op.execute(
        "CREATE POLICY tenant_delete ON channel_connections FOR DELETE "
        f"USING (tenant_id = {_TENANT_ATUAL})"
    )

    for tabela in ("channel_connections", "channel_credentials", "readiness_checks"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tabela} TO {ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON audit_log TO {ROLE}")


def downgrade() -> None:
    for tabela in reversed(TABELAS_NOVAS):
        op.drop_table(tabela)  # remove políticas, índices e privilégios junto

    op.drop_constraint("ck_conversations_iniciada_por", "conversations", type_="check")
    op.drop_column("conversations", "recebida_em_suspensao")
    op.drop_column("conversations", "iniciada_por")

    for nome in CHECKS_CONFIG:
        op.drop_constraint(nome, "tenant_config", type_="check")
    op.drop_column("tenant_config", "limite_mensagens_por_minuto")
    op.drop_column("tenant_config", "handoff_ttl_minutos")

    op.drop_constraint("ck_tenants_status", "tenants", type_="check")
    op.execute("ALTER TABLE tenants NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE tenants SET status = 'trial' WHERE status = 'em_configuracao'")
    op.execute("UPDATE tenants SET status = 'cancelado' WHERE status = 'encerrado'")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.drop_constraint("ck_tenants_slug_formato", "tenants", type_="check")
    op.drop_constraint("uq_tenants_slug", "tenants", type_="unique")
    for coluna in ("dados_apagados_em", "encerrado_em", "ativado_em", "slug"):
        op.drop_column("tenants", coluna)
