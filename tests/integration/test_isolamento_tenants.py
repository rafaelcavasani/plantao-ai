"""Isolamento entre empresas com RLS e o papel `plantao_app`: A, B e C (T055, princípio III, FR-021, FR-028).

Cada tabela com `tenant_id` está em `ENTIDADES_COBERTAS` (`tests/fakes/isolamento.py`) e passa pela matriz:
leitura própria, nenhuma linha alheia, escrita cruzada recusada e zero linhas sem contexto. A cobertura do registro
é conferida em `test_isolamento_cobertura.py`; a capacidade de a matriz detectar vazamento, em `test_isolamento_quebra.py`.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from db.session import get_session_factory
from tests.fakes.isolamento import (
    ENTIDADES_COBERTAS,
    Dados,
    popular_todas,
    sessao_real,
    verificar_busca_vetorial,
    verificar_entidade,
    verificar_tenants,
)

pytestmark = pytest.mark.integration

Trio = tuple[dict[str, uuid.UUID], dict[uuid.UUID, Dados]]


@pytest_asyncio.fixture
async def trio(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID, tenant_c: uuid.UUID
) -> Trio:
    ids = {"a": tenant_a, "b": tenant_b, "c": tenant_c}
    return ids, await popular_todas(db, ids)


async def test_papel_da_aplicacao_nao_e_superusuario(db: AsyncEngine) -> None:
    async with get_session_factory()() as s:
        row = (
            await s.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
    assert row == (False, False)


def test_registro_cobre_as_quinze_entidades_com_tenant_id() -> None:
    assert sorted(ENTIDADES_COBERTAS) == sorted(
        [
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
            "channel_connections",
            "channel_credentials",
            "readiness_checks",
            "audit_log",
        ]
    )


async def test_todas_as_entidades_estao_isoladas_entre_a_b_e_c(trio: Trio) -> None:
    """Uma só preparação de dados; as falhas de todas as entidades saem juntas na mensagem."""
    ids, dados = trio
    falhas: list[str] = []
    for tabela in sorted(ENTIDADES_COBERTAS):
        try:
            await verificar_entidade(sessao_real, tabela, ids, dados)
        except AssertionError as exc:
            falhas.append(f"{tabela}: {exc}")
    assert not falhas, "\n".join(falhas)


async def test_busca_vetorial_so_enxerga_os_trechos_da_propria_empresa(trio: Trio) -> None:
    ids, dados = trio
    await verificar_busca_vetorial(sessao_real, ids, dados)


async def test_cada_empresa_so_enxerga_a_propria_linha_em_tenants(trio: Trio) -> None:
    ids, _ = trio
    await verificar_tenants(sessao_real, ids)


async def test_credenciais_so_aparecem_para_a_empresa_dona(trio: Trio) -> None:
    ids, _ = trio
    for dono in ids.values():
        async with sessao_real(dono) as s:
            donos = (
                (await s.execute(text("SELECT tenant_id FROM channel_credentials"))).scalars().all()
            )
        assert set(donos) == {dono}
