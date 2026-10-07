"""Isolamento das tabelas do painel (spec 004, T011; princípio III).

A matriz geral (`test_isolamento_tenants.py`) já cobre `painel_agregado_hora` e `painel_situacao` para o papel
da aplicação. Aqui se prova o lado do painel: ele lê as duas empresas, o papel da aplicação continua isolado.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from db.models import PainelAgregadoHora, PainelSituacao
from db.painel import painel_session
from db.session import get_session_factory, tenant_session

pytestmark = pytest.mark.integration

HORA = datetime(2026, 10, 6, 12, tzinfo=UTC)


async def _gravar(tenant_id: uuid.UUID, mensagens: int) -> None:
    async with tenant_session(tenant_id) as s:
        s.add(PainelAgregadoHora(tenant_id=tenant_id, hora=HORA, msgs_lead=mensagens))
        s.add(PainelSituacao(tenant_id=tenant_id, conversas_abertas=mensagens))


async def test_painel_le_as_duas_empresas_e_soma(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await _gravar(tenant_a, 3)
    await _gravar(tenant_b, 5)
    async with painel_session() as s:
        linhas = (
            await s.execute(
                select(PainelAgregadoHora.tenant_id, PainelAgregadoHora.msgs_lead).order_by(
                    PainelAgregadoHora.msgs_lead
                )
            )
        ).all()
        total = (
            await s.execute(text("SELECT sum(msgs_lead) FROM painel_agregado_hora"))
        ).scalar_one()
    assert [(r.tenant_id, r.msgs_lead) for r in linhas] == [(tenant_a, 3), (tenant_b, 5)]
    assert total == 8


async def test_empresa_nao_enxerga_o_agregado_de_outra(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await _gravar(tenant_a, 3)
    await _gravar(tenant_b, 5)
    async with tenant_session(tenant_a) as s:
        ids = (await s.execute(select(PainelAgregadoHora.tenant_id))).scalars().all()
        sit = (await s.execute(select(PainelSituacao.tenant_id))).scalars().all()
    assert set(ids) == {tenant_a} and set(sit) == {tenant_a}


async def test_papel_da_aplicacao_sem_contexto_nao_le_agregado(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _gravar(tenant_a, 3)
    async with get_session_factory()() as s:
        assert (await s.execute(select(PainelAgregadoHora))).all() == []


async def test_empresa_nao_grava_agregado_em_nome_de_outra(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    with pytest.raises(Exception, match="row-level security"):
        async with tenant_session(tenant_a) as s:
            s.add(PainelAgregadoHora(tenant_id=tenant_b, hora=HORA))
            await s.flush()


async def test_painel_nao_escreve_agregado(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    with pytest.raises(Exception, match="permission denied"):
        async with painel_session() as s:
            await s.execute(
                text("INSERT INTO painel_situacao (tenant_id) VALUES (:t)"), {"t": tenant_a}
            )


async def test_tabelas_novas_tem_rls_forcado(admin_engine: AsyncEngine) -> None:
    async with AsyncSession(admin_engine) as s:
        linhas = (
            await s.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN ('painel_agregado_hora', 'painel_situacao') AND relkind = 'r'"
                )
            )
        ).all()
    assert sorted(tuple(r) for r in linhas) == [
        ("painel_agregado_hora", True, True),
        ("painel_situacao", True, True),
    ]
