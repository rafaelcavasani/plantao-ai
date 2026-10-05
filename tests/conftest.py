"""Configuração global dos testes.

As variáveis de ambiente precisam ser definidas ANTES de qualquer import de `core.config`, porque
`settings` é criado na importação. O banco de teste (`plantao_test`) é criado e migrado uma vez por sessão.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

from cryptography.fernet import Fernet

_ADMIN_URL = os.environ.get(
    "TEST_DATABASE_ADMIN_URL", "postgresql+asyncpg://plantao:plantao@localhost:5432/plantao_test"
)
_APP_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://plantao_app:plantao_app@localhost:5432/plantao_test"
)

os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = _APP_URL
os.environ["DATABASE_ADMIN_URL"] = _ADMIN_URL
os.environ["APP_DB_PASSWORD"] = "plantao_app"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["PII_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["PII_HASH_KEY"] = "chave-hash-somente-para-testes"
os.environ["WHATSAPP_WEBHOOK_SECRET"] = "segredo-de-teste"
os.environ["OPENROUTER_API_KEY"] = "sk-teste"
os.environ["PILOT_TENANT_ID"] = ""

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from db.models import Tenant, TenantConfig  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent


def alembic_config(url: str) -> Config:
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "db" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


async def recriar_banco(admin_url: str) -> None:
    """Descarta e recria o banco indicado em `admin_url` usando o banco de manutenção `postgres`."""
    url = make_url(admin_url)
    engine = create_async_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    nome = url.database
    async with engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{nome}"'))
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def banco_de_teste() -> Iterator[None]:
    """Cria `plantao_test` e aplica as migrações. Pula testes de integração se o Postgres estiver fora."""
    try:
        asyncio.run(recriar_banco(_ADMIN_URL))
    except Exception as exc:  # noqa: BLE001
        os.environ["_BANCO_INDISPONIVEL"] = f"{type(exc).__name__}"
        yield
        return
    command.upgrade(alembic_config(_ADMIN_URL), "head")
    yield


@pytest_asyncio.fixture
async def admin_engine() -> AsyncIterator[AsyncEngine]:
    if os.environ.get("_BANCO_INDISPONIVEL"):
        pytest.skip("Postgres de teste indisponível")
    engine = create_async_engine(_ADMIN_URL, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(admin_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """Banco limpo para cada teste (TRUNCATE de todas as tabelas de dados). Devolve o engine admin."""
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE handoff_log, llm_calls, messages, conversations, leads, appointments, "
                "billing_events, usage_metrics, tenant_knowledge, knowledge_documents, "
                "tenant_config, tenants CASCADE"
            )
        )
    yield admin_engine


async def criar_tenant(
    engine: AsyncEngine, nome: str = "Clínica Teste", **config: object
) -> uuid.UUID:
    """Cria tenant + config (como admin, ignorando RLS) e devolve o id."""
    tenant_id = uuid.uuid4()
    valores: dict[str, object] = {
        "tom_de_voz": "Cordial e direto.",
        "horario_funcionamento": {"seg_sex": "08:00-18:00"},
        "limite_desconto_percentual": 10.0,
        "topicos_proibidos": ["garantia de resultado"],
        "confianca_minima_handoff": 0.7,
        "palavras_gatilho": ["processo", "procon", "cancelar tudo", "advogado", "reclamação"],
        "router_confidence_threshold": 0.6,
        "min_similarity": 0.30,
    }
    valores.update(config)
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Tenant(id=tenant_id, nome_empresa=nome, nicho="clinica", plano="recepcionista"))
        await session.flush()
        session.add(TenantConfig(tenant_id=tenant_id, **valores))
        await session.commit()
    return tenant_id


@pytest_asyncio.fixture
async def tenant_a(db: AsyncEngine) -> uuid.UUID:
    return await criar_tenant(db, "Clínica A")


@pytest_asyncio.fixture
async def tenant_b(db: AsyncEngine) -> uuid.UUID:
    return await criar_tenant(db, "Clínica B")
