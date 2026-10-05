"""Trilha de auditoria por campo (FR-029)."""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from core.tenancy import registrar_mudanca
from db.models import AuditLog, TenantConfig
from db.session import tenant_session

pytestmark = pytest.mark.integration


async def _linhas(tenant_id: uuid.UUID) -> list[AuditLog]:
    async with tenant_session(tenant_id) as s:
        return list((await s.execute(select(AuditLog).order_by(AuditLog.campo))).scalars().all())


async def test_grava_uma_linha_por_campo(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    async with tenant_session(tenant_a) as s:
        await registrar_mudanca(s, tenant_a, "config", "min_similarity", 0.3, 0.5, "ana")
        await registrar_mudanca(
            s, tenant_a, "config", "topicos_proibidos", ["a"], ["a", "b"], "ana"
        )

    linhas = await _linhas(tenant_a)
    assert [linha.campo for linha in linhas] == ["min_similarity", "topicos_proibidos"]
    sim = linhas[0]
    assert (sim.entidade, sim.valor_anterior, sim.valor_novo, sim.operador) == (
        "config",
        0.3,
        0.5,
        "ana",
    )
    assert sim.criado_em is not None
    assert linhas[1].valor_anterior == ["a"]
    assert linhas[1].valor_novo == ["a", "b"]


async def test_entra_na_mesma_transacao_da_mudanca(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    with pytest.raises(RuntimeError):
        async with tenant_session(tenant_a) as s:
            cfg = await s.get(TenantConfig, tenant_a)
            assert cfg is not None
            cfg.min_similarity = 0.9
            await registrar_mudanca(s, tenant_a, "config", "min_similarity", 0.3, 0.9, "ana")
            await s.flush()
            raise RuntimeError("falha depois da mudança")

    assert await _linhas(tenant_a) == []
    async with tenant_session(tenant_a) as s:
        cfg = await s.get(TenantConfig, tenant_a)
        assert cfg is not None
        assert cfg.min_similarity == 0.30


async def test_credencial_nunca_aparece(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    async with tenant_session(tenant_a) as s:
        await registrar_mudanca(
            s, tenant_a, "conexao", "credencial", "chave-antiga-123", "chave-nova-456", "ana"
        )
        await registrar_mudanca(s, tenant_a, "conexao", "credencial", None, "chave-nova-456", "ana")

    linhas = await _linhas(tenant_a)
    assert len(linhas) == 2
    for linha in linhas:
        assert linha.valor_novo == "<atualizada>"
        assert linha.valor_anterior in (None, "<atualizada>")
    async with tenant_session(tenant_a) as s:
        bruto = (await s.execute(text("SELECT row_to_json(a)::text FROM audit_log a"))).scalars()
        for texto in bruto:
            assert "chave-" not in texto


async def test_aplicacao_nao_altera_nem_apaga(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    async with tenant_session(tenant_a) as s:
        await registrar_mudanca(s, tenant_a, "estado", "status", "ativo", "suspenso", "ana")

    for comando in ("UPDATE audit_log SET operador = 'outro'", "DELETE FROM audit_log"):
        with pytest.raises(DBAPIError):
            async with tenant_session(tenant_a) as s:
                await s.execute(text(comando))

    assert [linha.operador for linha in await _linhas(tenant_a)] == ["ana"]


async def test_auditoria_isolada_por_empresa(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    async with tenant_session(tenant_a) as s:
        await registrar_mudanca(s, tenant_a, "estado", "status", "ativo", "suspenso", "ana")

    assert await _linhas(tenant_b) == []
