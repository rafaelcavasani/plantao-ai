"""Configuração global dos testes.

As variáveis de ambiente precisam ser definidas ANTES de qualquer import de `core.config`, porque
`settings` é criado na importação. O banco de teste (`plantao_test`) é criado e migrado uma vez por sessão.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

_ADMIN_URL = os.environ.get(
    "TEST_DATABASE_ADMIN_URL", "postgresql+asyncpg://plantao:plantao@localhost:5432/plantao_test"
)
_APP_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://plantao_app:plantao_app@localhost:5432/plantao_test"
)

_PAINEL_URL = os.environ.get(
    "TEST_DATABASE_PAINEL_URL",
    "postgresql+asyncpg://plantao_painel:plantao_painel@localhost:5432/plantao_test",
)

os.environ["ENV"] = "test"
os.environ["DATABASE_PAINEL_URL"] = _PAINEL_URL
os.environ["OPERADORES"] = "operador@exemplo.com:operacao,leitor@exemplo.com:leitura"
os.environ["DATABASE_URL"] = _APP_URL
os.environ["DATABASE_ADMIN_URL"] = _ADMIN_URL
os.environ["APP_DB_PASSWORD"] = "plantao_app"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["PII_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["PII_HASH_KEY"] = "chave-hash-somente-para-testes"
os.environ["OPENROUTER_API_KEY"] = "sk-teste"
os.environ["PURGE_DRENAGEM_SEGUNDOS"] = "0"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from db.models import ChannelConnection, ChannelCredential, Tenant, TenantConfig  # noqa: E402
from tests.fakes.painel import AdminApi  # noqa: E402

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
                "TRUNCATE readiness_checks, audit_log, channel_credentials, channel_connections, "
                "handoff_log, llm_calls, messages, conversations, leads, appointments, "
                "billing_events, usage_metrics, tenant_knowledge, knowledge_documents, "
                "painel_agregado_hora, painel_situacao, tenant_config, tenants CASCADE"
            )
        )
    yield admin_engine


async def criar_tenant(
    engine: AsyncEngine,
    nome: str = "Clínica Teste",
    *,
    slug: str | None = None,
    status: str = "ativo",
    **config: object,
) -> uuid.UUID:
    """Cria tenant + config (como admin, ignorando RLS) e devolve o id.

    `status` padrão é `ativo` para os testes de pipeline continuarem válidos.
    """
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
    base = re.sub(r"[^a-z0-9]+", "-", nome.lower().encode("ascii", "ignore").decode()).strip("-")
    slug = slug or f"{base or 'empresa'}-{uuid.uuid4().hex[:8]}"

    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(
            Tenant(
                id=tenant_id,
                nome_empresa=nome,
                slug=slug,
                nicho="clinica",
                plano="recepcionista",
                status=status,
            )
        )
        await session.flush()
        session.add(TenantConfig(tenant_id=tenant_id, **valores))
        await session.commit()
    return tenant_id


@dataclass(frozen=True)
class ConexaoCriada:
    """Valores em claro de uma conexão criada por `criar_conexao` (só existem no teste)."""

    connection_id: uuid.UUID
    instance_name: str
    webhook_secret: str
    api_key: str


async def criar_conexao(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    instance_name: str | None = None,
    webhook_secret: str | None = None,
    api_key: str | None = None,
) -> ConexaoCriada:
    """Cadastra a conexão de canal da empresa (como admin) e devolve os valores em claro."""
    instance_name = instance_name or f"inst-{uuid.uuid4().hex[:10]}"
    webhook_secret = webhook_secret or f"segredo-{uuid.uuid4().hex}"
    api_key = api_key or f"chave-{uuid.uuid4().hex}"
    from core.security.crypto import get_cripto

    async with AsyncSession(engine, expire_on_commit=False) as session:
        conexao = ChannelConnection(
            tenant_id=tenant_id, canal="whatsapp", provedor="evolution", instance_name=instance_name
        )
        session.add(conexao)
        await session.flush()
        session.add(
            ChannelCredential(
                connection_id=conexao.id,
                tenant_id=tenant_id,
                webhook_secret_hash=hashlib.sha256(webhook_secret.encode()).hexdigest(),
                api_key_enc=get_cripto().encrypt(api_key),
            )
        )
        await session.commit()
    return ConexaoCriada(conexao.id, instance_name, webhook_secret, api_key)


@pytest_asyncio.fixture
async def tenant_a(db: AsyncEngine) -> uuid.UUID:
    return await criar_tenant(db, "Clínica A")


@pytest_asyncio.fixture
async def tenant_b(db: AsyncEngine) -> uuid.UUID:
    return await criar_tenant(db, "Clínica B")


@pytest_asyncio.fixture
async def tenant_c(db: AsyncEngine) -> uuid.UUID:
    return await criar_tenant(db, "Clínica C")


@pytest_asyncio.fixture
async def admin_api(db: AsyncEngine) -> AsyncIterator["AdminApi"]:  # noqa: UP037
    """API de operação do painel com Redis e fila falsos e sessões criadas direto no Redis (spec 004)."""
    import httpx
    from fakeredis import FakeAsyncRedis

    from apps.api.admin.escrita import get_canal
    from apps.api.deps import get_queue, get_redis
    from apps.api.main import app
    from tests.fakes.channel import FakeChannel, FakeQueue
    from tests.fakes.painel import BASE, AdminApi

    redis = FakeAsyncRedis()
    fila = FakeQueue()
    canal = FakeChannel()
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_queue] = lambda: fila
    app.dependency_overrides[get_canal] = lambda: canal
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as cliente:
        yield AdminApi(cliente, redis, fila, canal)
    app.dependency_overrides.clear()
    await redis.aclose()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Testes marcados `lento` (carga de 1 milhão de mensagens) só rodam com `-m lento`."""
    if "lento" in (config.getoption("-m") or ""):
        return
    pular = pytest.mark.skip(reason="teste lento: rode com `-m lento`")
    for item in items:
        if "lento" in item.keywords:
            item.add_marker(pular)


@pytest.fixture
def relogio_do_limite(monkeypatch: pytest.MonkeyPatch) -> None:
    """Congela a janela de 1 minuto do limite de mensagens (`rl:{tenant}:{minuto}`).

    Sem isso, um teste que envia várias mensagens pode atravessar a virada do minuto e contar em duas chaves.
    """
    from types import SimpleNamespace

    monkeypatch.setattr("apps.api.ratelimit.time", SimpleNamespace(time=lambda: 1_700_000_040.0))
