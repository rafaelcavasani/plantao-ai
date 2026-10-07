"""Desempenho do painel com a carga da spec (spec 004, T082; SC-002).

50 empresas e cerca de 1 milhão de mensagens: a visão geral e a ficha precisam abrir em até 3 s. É um teste
lento (insere 1 milhão de linhas); rode com `pytest -m lento tests/integration/test_painel_desempenho.py`.
"""

import time
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from core.painel.agregacao import recalcular_todas
from scripts.painel_seed import semear_historico
from tests.conftest import criar_tenant
from tests.fakes.painel import AdminApi

pytestmark = [pytest.mark.integration, pytest.mark.lento]

EMPRESAS = 50
DIAS = 30
CONVERSAS_POR_DIA = (
    333  # 50 empresas x 30 dias x 333 conversas x 2 mensagens = ~1 milhão de mensagens
)
LIMITE_SEGUNDOS = 3.0


async def test_visao_geral_e_ficha_abrem_em_ate_3_segundos(
    admin_api: AdminApi, db: AsyncEngine
) -> None:
    ids: list[uuid.UUID] = []
    for i in range(EMPRESAS):
        ids.append(await criar_tenant(db, f"Carga {i:02d}", slug=f"carga-{i:02d}"))
    for tenant_id in ids:
        async with AsyncSession(db) as s, s.begin():
            await semear_historico(s, tenant_id, dias=DIAS, conversas_por_dia=CONVERSAS_POR_DIA)
    async with db.connect() as conn:
        mensagens = (await conn.execute(text("SELECT count(*) FROM messages"))).scalar_one()
    assert mensagens >= 900_000, f"a carga deveria ter ~1 milhão de mensagens, tem {mensagens}"

    inicio = time.perf_counter()
    resultado = await recalcular_todas(agora=datetime.now(UTC), janela_horas=DIAS * 24 + 24)
    agregacao = time.perf_counter() - inicio
    assert resultado.empresas == EMPRESAS and resultado.falhas == []
    print(f"\nagregação de {mensagens:,} mensagens: {agregacao:.1f} s")

    for caminho in (
        "/admin/visao-geral?periodo=30d",
        "/admin/empresas?periodo=30d&tamanho=50",
        "/admin/empresas/carga-00?periodo=30d",
        "/admin/empresas/carga-00/serie?periodo=30d",
    ):
        inicio = time.perf_counter()
        r = await admin_api.get(caminho)
        duracao = time.perf_counter() - inicio
        assert r.status_code == 200, caminho
        assert duracao <= LIMITE_SEGUNDOS, (
            f"{caminho} levou {duracao:.2f} s (limite {LIMITE_SEGUNDOS} s)"
        )
        print(f"{caminho}: {duracao:.3f} s")
