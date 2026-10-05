"""Migrações reversíveis (T020).

Usa um banco descartável próprio para não interferir no banco de teste compartilhado.
"""

import asyncio
import os

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import _ADMIN_URL, alembic_config, recriar_banco

pytestmark = pytest.mark.integration


async def _tabelas(url: str) -> set[str]:
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        resultado = {r[0] for r in rows}
    await engine.dispose()
    return resultado


def test_upgrade_downgrade_upgrade() -> None:
    if os.environ.get("_BANCO_INDISPONIVEL"):
        pytest.skip("Postgres de teste indisponível")
    url = (
        make_url(_ADMIN_URL)
        .set(database="plantao_migracao_teste")
        .render_as_string(hide_password=False)
    )
    asyncio.run(recriar_banco(url))
    cfg = alembic_config(url)

    command.upgrade(cfg, "head")
    tabelas = asyncio.run(_tabelas(url))
    assert {"tenants", "messages", "llm_calls", "knowledge_documents", "handoff_log"} <= tabelas

    command.downgrade(cfg, "base")
    tabelas = asyncio.run(_tabelas(url))
    assert tabelas <= {"alembic_version"}

    command.upgrade(cfg, "head")
    assert "llm_calls" in asyncio.run(_tabelas(url))
