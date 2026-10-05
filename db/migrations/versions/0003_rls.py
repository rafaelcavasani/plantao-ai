"""papel plantao_app, Row-Level Security e índice vetorial HNSW

O papel `plantao_app` não é superusuário e não tem BYPASSRLS. A aplicação conecta com ele. As políticas
filtram por `app.tenant_id`, definido por transação (`db.session.tenant_session`). `FORCE ROW LEVEL
SECURITY` aplica as políticas também ao dono das tabelas.

A senha do papel vem de `APP_DB_PASSWORD` (padrão de desenvolvimento: `plantao_app`). Em produção, defina
um valor próprio antes de rodar esta migração.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-04
"""

from collections.abc import Sequence

from alembic import op

from core.config import settings

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "plantao_app"
TABELAS_COM_TENANT = (
    "tenant_config",
    "tenant_knowledge",
    "knowledge_documents",
    "conversations",
    "messages",
    "leads",
    "appointments",
    "billing_events",
    "usage_metrics",
    "handoff_log",
    "llm_calls",
)
_TENANT_ATUAL = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    senha = settings.app_db_password.replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} LOGIN PASSWORD '{senha}' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    op.execute(f"GRANT SELECT ON tenants TO {ROLE}")

    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON tenants USING (id = {_TENANT_ATUAL})")

    for tabela in TABELAS_COM_TENANT:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tabela} TO {ROLE}")
        op.execute(f"ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tabela} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {tabela} "
            f"USING (tenant_id = {_TENANT_ATUAL}) WITH CHECK (tenant_id = {_TENANT_ATUAL})"
        )

    op.execute(
        "CREATE INDEX ix_tenant_knowledge_embedding_hnsw ON tenant_knowledge "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tenant_knowledge_embedding_hnsw")
    for tabela in (*TABELAS_COM_TENANT, "tenants"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tabela}")
        op.execute(f"ALTER TABLE {tabela} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tabela} DISABLE ROW LEVEL SECURITY")
    # Remove os privilégios do papel neste banco. O papel em si é global do cluster e permanece.
    op.execute(f"DROP OWNED BY {ROLE}")
