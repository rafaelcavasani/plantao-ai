"""Cobertura do isolamento: toda tabela com `tenant_id` tem RLS forçado, política e entrada no registro (T056).

Uma tabela nova com `tenant_id` sem RLS, sem política ou fora de `ENTIDADES_COBERTAS` derruba este teste, o que
obriga quem a criou a incluí-la na matriz de isolamento (research R-14, item 2; FR-028).
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from tests.fakes.isolamento import ENTIDADES_COBERTAS

pytestmark = pytest.mark.integration

TABELAS_COM_TENANT_ID = """
SELECT c.relname AS tabela, c.relrowsecurity AS rls, c.relforcerowsecurity AS forcado,
       COALESCE(
           (SELECT array_agg(pg_get_expr(p.polqual, p.polrelid)) FROM pg_policy p
            WHERE p.polrelid = c.oid AND p.polqual IS NOT NULL),
           ARRAY[]::text[]
       ) AS filtros
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
  AND EXISTS (
      SELECT 1 FROM information_schema.columns col
      WHERE col.table_schema = 'public' AND col.table_name = c.relname AND col.column_name = 'tenant_id'
  )
ORDER BY c.relname
"""


async def problemas_de_cobertura(conn: AsyncConnection) -> list[str]:
    problemas: list[str] = []
    for linha in (await conn.execute(text(TABELAS_COM_TENANT_ID))).all():
        tabela = linha.tabela
        if not linha.rls:
            problemas.append(f"{tabela}: sem ROW LEVEL SECURITY")
        if not linha.forcado:
            problemas.append(f"{tabela}: sem FORCE ROW LEVEL SECURITY")
        if not any("app.tenant_id" in filtro for filtro in linha.filtros):
            problemas.append(f"{tabela}: sem política que filtre por app.tenant_id")
        if tabela not in ENTIDADES_COBERTAS:
            problemas.append(
                f"{tabela}: fora de ENTIDADES_COBERTAS (inclua na matriz de isolamento)"
            )
    return problemas


async def test_todas_as_tabelas_com_tenant_id_estao_protegidas_e_cobertas(
    admin_engine: AsyncEngine,
) -> None:
    async with admin_engine.connect() as conn:
        assert await problemas_de_cobertura(conn) == []


async def test_o_registro_nao_tem_entidade_que_nao_existe_no_banco(
    admin_engine: AsyncEngine,
) -> None:
    async with admin_engine.connect() as conn:
        tabelas = {
            linha.tabela for linha in (await conn.execute(text(TABELAS_COM_TENANT_ID))).all()
        }
    assert set(ENTIDADES_COBERTAS) == tabelas


async def test_tabela_tenants_tem_rls_forcado_e_politica(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        linha = (
            await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity, "
                    "(SELECT count(*) FROM pg_policy WHERE polrelid = c.oid) "
                    "FROM pg_class c WHERE relname = 'tenants' AND relkind = 'r'"
                )
            )
        ).one()
    # 2 políticas: o isolamento por empresa e a leitura do painel (`painel_leitura`, só SELECT, spec 004).
    assert linha == (True, True, 2)


@pytest.mark.parametrize(
    ("ddl", "esperado"),
    [
        (
            "CREATE TABLE tabela_nova (id int, tenant_id uuid)",
            ["sem ROW LEVEL SECURITY", "sem FORCE", "sem política", "fora de ENTIDADES_COBERTAS"],
        ),
        (
            "CREATE TABLE tabela_nova (id int, tenant_id uuid);"
            "ALTER TABLE tabela_nova ENABLE ROW LEVEL SECURITY;"
            "ALTER TABLE tabela_nova FORCE ROW LEVEL SECURITY;"
            "CREATE POLICY p ON tabela_nova USING (true)",
            ["sem política", "fora de ENTIDADES_COBERTAS"],
        ),
        (
            "CREATE TABLE tabela_nova (id int, tenant_id uuid);"
            "ALTER TABLE tabela_nova ENABLE ROW LEVEL SECURITY;"
            "ALTER TABLE tabela_nova FORCE ROW LEVEL SECURITY;"
            "CREATE POLICY p ON tabela_nova USING (tenant_id = "
            "NULLIF(current_setting('app.tenant_id', true), '')::uuid)",
            ["fora de ENTIDADES_COBERTAS"],
        ),
    ],
)
async def test_a_verificacao_detecta_tabela_nova_desprotegida_ou_fora_do_registro(
    admin_engine: AsyncEngine, ddl: str, esperado: list[str]
) -> None:
    async with admin_engine.connect() as conn:
        transacao = await conn.begin()
        try:
            for comando in ddl.split(";"):
                await conn.execute(text(comando))
            problemas = [
                p for p in await problemas_de_cobertura(conn) if p.startswith("tabela_nova")
            ]
        finally:
            await transacao.rollback()
    assert len(problemas) == len(esperado)
    for trecho in esperado:
        assert any(trecho in p for p in problemas), (trecho, problemas)
