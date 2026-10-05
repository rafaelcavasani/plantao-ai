"""Migrações reversíveis (T020).

Usa um banco descartável próprio para não interferir no banco de teste compartilhado.
"""

import asyncio
import os
import re
import uuid

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from db.models import ChannelConnection
from db.session import get_session_factory, tenant_session
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


# ---------------------------------------------------------------------------------------------
# Migração 0004 (multi-tenancy)
# ---------------------------------------------------------------------------------------------

TABELAS_NOVAS = {"channel_connections", "channel_credentials", "readiness_checks", "audit_log"}


def _url_migracao() -> str:
    return (
        make_url(_ADMIN_URL)
        .set(database="plantao_migracao_teste")
        .render_as_string(hide_password=False)
    )


async def _consulta(url: str, sql: str, **params: object) -> list[tuple[object, ...]]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params)
            return [tuple(r) for r in result] if result.returns_rows else []
    finally:
        await engine.dispose()


def _sql(url: str, sql: str, **params: object) -> list[tuple[object, ...]]:
    return asyncio.run(_consulta(url, sql, **params))


@pytest.fixture
def banco_migracao() -> str:
    if os.environ.get("_BANCO_INDISPONIVEL"):
        pytest.skip("Postgres de teste indisponível")
    url = _url_migracao()
    asyncio.run(recriar_banco(url))
    return url


def _inserir_legado(url: str) -> None:
    for nome, status in [
        ("Clínica Sorriso (piloto)", "ativo"),
        ("Clínica Nova", "trial"),
        ("Clínica Velha", "cancelado"),
        ("Clínica Pausada", "suspenso"),
        ("Clínica Nova", "trial"),  # nome repetido: o slug precisa continuar único
    ]:
        _sql(
            url,
            "INSERT INTO tenants (id, nome_empresa, nicho, plano, status) "
            "VALUES (gen_random_uuid(), :n, 'clinica', 'recepcionista', :s)",
            n=nome,
            s=status,
        )


def test_0004_reversivel_e_mapeia_status(banco_migracao: str) -> None:
    url = banco_migracao
    cfg = alembic_config(url)
    command.upgrade(cfg, "0003")
    _inserir_legado(url)

    command.upgrade(cfg, "head")
    assert TABELAS_NOVAS <= asyncio.run(_tabelas(url))
    status = {r[0]: r[1] for r in _sql(url, "SELECT nome_empresa || id::text, status FROM tenants")}
    assert sorted(status.values()) == sorted(
        ["ativo", "em_configuracao", "encerrado", "suspenso", "em_configuracao"]
    )
    slugs = [r[0] for r in _sql(url, "SELECT slug FROM tenants")]
    assert "clinica-sorriso-piloto" in slugs
    assert len(set(slugs)) == len(slugs) == 5
    assert all(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", s) for s in slugs)

    command.downgrade(cfg, "0003")
    assert not (TABELAS_NOVAS & asyncio.run(_tabelas(url)))
    assert sorted(r[0] for r in _sql(url, "SELECT status FROM tenants")) == sorted(
        ["ativo", "trial", "cancelado", "suspenso", "trial"]
    )
    colunas = {
        r[0]
        for r in _sql(
            url,
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'tenants'",
        )
    }
    assert not ({"slug", "ativado_em", "encerrado_em", "dados_apagados_em"} & colunas)

    command.upgrade(cfg, "head")
    assert TABELAS_NOVAS <= asyncio.run(_tabelas(url))


def test_0004_restricoes_de_tenants(banco_migracao: str) -> None:
    url = banco_migracao
    command.upgrade(alembic_config(url), "head")

    with pytest.raises(DBAPIError):
        _sql(
            url,
            "INSERT INTO tenants (id, nome_empresa, nicho, plano, status, slug) "
            "VALUES (gen_random_uuid(), 'X', 'n', 'p', 'trial', 'x-ok')",
        )
    with pytest.raises(DBAPIError):
        _sql(
            url,
            "INSERT INTO tenants (id, nome_empresa, nicho, plano, status, slug) "
            "VALUES (gen_random_uuid(), 'X', 'n', 'p', 'ativo', 'Slug Ruim')",
        )
    insert = (
        "INSERT INTO tenants (id, nome_empresa, nicho, plano, status, slug) "
        "VALUES (gen_random_uuid(), 'X', 'n', 'p', :s, 'repetido')"
    )
    _sql(url, insert, s="em_configuracao")
    with pytest.raises(DBAPIError):
        _sql(url, insert, s="ativo")


def test_0004_checks_de_tenant_config(banco_migracao: str) -> None:
    url = banco_migracao
    command.upgrade(alembic_config(url), "head")
    _sql(
        url,
        "INSERT INTO tenants (id, nome_empresa, nicho, plano, status, slug) "
        "VALUES ('00000000-0000-0000-0000-000000000001', 'X', 'n', 'p', 'ativo', 'x')",
    )
    base = {
        "confianca_minima_handoff": 0.7,
        "router_confidence_threshold": 0.6,
        "min_similarity": 0.3,
        "limite_desconto_percentual": 10.0,
        "handoff_ttl_minutos": 60,
        "limite_mensagens_por_minuto": 60,
    }

    def inserir(**mudancas: float) -> None:
        v = {**base, **mudancas}
        _sql(
            url,
            "INSERT INTO tenant_config (tenant_id, tom_de_voz, horario_funcionamento, "
            "limite_desconto_percentual, topicos_proibidos, confianca_minima_handoff, "
            "palavras_gatilho, router_confidence_threshold, min_similarity, "
            "handoff_ttl_minutos, limite_mensagens_por_minuto) VALUES "
            "('00000000-0000-0000-0000-000000000001', '', '{}', :limite_desconto_percentual, "
            "'[]', :confianca_minima_handoff, '[]', :router_confidence_threshold, "
            ":min_similarity, :handoff_ttl_minutos, :limite_mensagens_por_minuto)",
            **v,
        )

    for campo, ruim in [
        ("confianca_minima_handoff", 1.5),
        ("router_confidence_threshold", -0.1),
        ("min_similarity", 2),
        ("limite_desconto_percentual", 101),
        ("handoff_ttl_minutos", 0),
        ("handoff_ttl_minutos", 1441),
        ("limite_mensagens_por_minuto", 0),
        ("limite_mensagens_por_minuto", 6001),
    ]:
        with pytest.raises(DBAPIError):
            inserir(**{campo: ruim})
    inserir()


def test_0004_rls_e_privilegios(banco_migracao: str) -> None:
    url = banco_migracao
    command.upgrade(alembic_config(url), "head")

    for tabela in TABELAS_NOVAS:
        row = _sql(
            url,
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t",
            t=tabela,
        )[0]
        assert row == (True, True), tabela

    priv = {
        (t, p): _sql(
            url,
            "SELECT has_table_privilege('plantao_app', CAST(:t AS text), CAST(:p AS text))",
            t=t,
            p=p,
        )[0][0]
        for t in ("audit_log", "channel_connections", "channel_credentials", "readiness_checks")
        for p in ("SELECT", "INSERT", "UPDATE", "DELETE")
    }
    assert priv[("audit_log", "SELECT")] and priv[("audit_log", "INSERT")]
    assert not priv[("audit_log", "UPDATE")]
    assert not priv[("audit_log", "DELETE")]
    for t in ("channel_connections", "channel_credentials", "readiness_checks"):
        assert all(priv[(t, p)] for p in ("SELECT", "INSERT", "UPDATE", "DELETE")), t

    # audit_log sem chave estrangeira (sobrevive à exclusão da empresa)
    fks = _sql(
        url,
        "SELECT count(*) FROM information_schema.table_constraints "
        "WHERE table_name = 'audit_log' AND constraint_type = 'FOREIGN KEY'",
    )
    assert fks[0][0] == 0


async def test_roteamento_le_sem_tenant_e_escrita_cruzada_falha(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    async with tenant_session(tenant_a) as s:
        s.add(
            ChannelConnection(
                tenant_id=tenant_a, canal="whatsapp", provedor="evolution", instance_name="inst-a"
            )
        )

    # sem contexto de tenant, o diretório de roteamento é legível
    async with get_session_factory()() as s:
        nomes = (await s.execute(select(ChannelConnection.instance_name))).scalars().all()
        assert nomes == ["inst-a"]

    # empresa B lê o diretório, mas não escreve em nome de A
    async with tenant_session(tenant_b) as s:
        nomes = (await s.execute(select(ChannelConnection.instance_name))).scalars().all()
        assert nomes == ["inst-a"]
    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_b) as s:
            s.add(
                ChannelConnection(
                    tenant_id=tenant_a,
                    canal="web",
                    provedor="evolution",
                    instance_name="inst-forjada",
                )
            )
    async with tenant_session(tenant_b) as s:
        await s.execute(text("UPDATE channel_connections SET instance_name = 'roubada'"))
    async with tenant_session(tenant_a) as s:
        nomes = (await s.execute(select(ChannelConnection.instance_name))).scalars().all()
        assert nomes == ["inst-a"]
