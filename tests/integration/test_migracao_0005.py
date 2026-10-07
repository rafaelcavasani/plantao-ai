"""Migração 0005 reversível (spec 004, T012).

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


async def _consulta(url: str, sql: str) -> list[tuple[object, ...]]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql))
            return [tuple(r) for r in result] if result.returns_rows else []
    finally:
        await engine.dispose()


def _sql(url: str, sql: str) -> list[tuple[object, ...]]:
    return asyncio.run(_consulta(url, sql))


def test_0005_reversivel() -> None:
    if os.environ.get("_BANCO_INDISPONIVEL"):
        pytest.skip("Postgres de teste indisponível")
    url = (
        make_url(_ADMIN_URL)
        .set(database="plantao_migracao_teste_0005")
        .render_as_string(hide_password=False)
    )
    asyncio.run(recriar_banco(url))
    cfg = alembic_config(url)

    command.upgrade(cfg, "0004")
    _sql(
        url,
        "INSERT INTO tenants (id, nome_empresa, nicho, plano, status, slug) "
        "VALUES (gen_random_uuid(), 'Clínica', 'clinica', 'recepcionista', 'ativo', 'clinica')",
    )

    command.upgrade(cfg, "0005")
    tabelas = {r[0] for r in _sql(url, "SELECT tablename FROM pg_tables WHERE schemaname='public'")}
    assert {"painel_agregado_hora", "painel_situacao"} <= tabelas
    assert _sql(url, "SELECT versao FROM tenants") == [(1,)]
    assert _sql(url, "SELECT rolname FROM pg_roles WHERE rolname = 'plantao_painel'") == [
        ("plantao_painel",)
    ]

    command.downgrade(cfg, "0004")
    tabelas = {r[0] for r in _sql(url, "SELECT tablename FROM pg_tables WHERE schemaname='public'")}
    assert not ({"painel_agregado_hora", "painel_situacao"} & tabelas)
    colunas = {
        r[0]
        for r in _sql(
            url,
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'tenants'",
        )
    }
    assert "versao" not in colunas
    # A estrutura da 0004 continua intacta e a empresa criada antes segue lá.
    assert {"channel_connections", "audit_log", "readiness_checks"} <= tabelas
    assert _sql(url, "SELECT slug FROM tenants") == [("clinica",)]
    politicas = _sql(url, "SELECT policyname FROM pg_policies WHERE policyname = 'painel_leitura'")
    assert politicas == []

    command.upgrade(cfg, "head")  # subir de novo depois de descer
    assert _sql(url, "SELECT versao FROM tenants") == [(1,)]
