"""A suíte de isolamento detecta quebra de propósito (T057, research R-14 item 3, SC-003).

Numa transação que é sempre revertida, a política de uma tabela é removida, o RLS é desligado ou a política é
trocada por uma aberta. Em seguida a mesma matriz de `test_isolamento_tenants.py` roda como o papel da
aplicação, dentro da transação, e PRECISA falhar com `AssertionError` (vazamento ou perda de acesso).
O controle sem quebra prova que a falha vem da quebra e não do modo de execução.
"""

import itertools
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.fakes.isolamento import (
    Dados,
    popular_todas,
    sessao_na_transacao,
    verificar_matriz,
)

pytestmark = pytest.mark.integration

QUEBRAS: dict[str, list[str]] = {
    "remover_politica": ["DROP POLICY tenant_isolation ON {t}"],
    "desligar_rls": ["ALTER TABLE {t} DISABLE ROW LEVEL SECURITY"],
    "politica_aberta": [
        "DROP POLICY tenant_isolation ON {t}",
        "CREATE POLICY tenant_isolation ON {t} USING (true) WITH CHECK (true)",
    ],
}
TABELAS = ["conversations", "tenant_knowledge", "channel_credentials", "audit_log"]


@pytest_asyncio.fixture
async def trio(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID, tenant_c: uuid.UUID
) -> tuple[dict[str, uuid.UUID], dict[uuid.UUID, Dados]]:
    ids = {"a": tenant_a, "b": tenant_b, "c": tenant_c}
    return ids, await popular_todas(db, ids)


async def test_controle_a_matriz_passa_dentro_da_transacao_sem_quebra(
    db: AsyncEngine, trio: tuple[dict[str, uuid.UUID], dict[uuid.UUID, Dados]]
) -> None:
    ids, dados = trio
    async with db.connect() as conn:
        transacao = await conn.begin()
        try:
            await verificar_matriz(sessao_na_transacao(conn), ids, dados)
        finally:
            await transacao.rollback()


async def test_a_matriz_falha_quando_o_isolamento_e_quebrado(
    db: AsyncEngine, trio: tuple[dict[str, uuid.UUID], dict[uuid.UUID, Dados]]
) -> None:
    """Cada quebra roda na própria transação revertida; as não detectadas saem juntas na mensagem."""
    ids, dados = trio
    nao_detectadas: list[str] = []
    for tabela, quebra in itertools.product(TABELAS, sorted(QUEBRAS)):
        async with db.connect() as conn:
            transacao = await conn.begin()
            try:
                for comando in QUEBRAS[quebra]:
                    await conn.execute(text(comando.format(t=tabela)))
                try:
                    await verificar_matriz(sessao_na_transacao(conn), ids, dados)
                except AssertionError:
                    continue  # detectada, como esperado
                nao_detectadas.append(f"{quebra} em {tabela}")
            finally:
                await transacao.rollback()
    assert not nao_detectadas, f"a matriz não detectou: {nao_detectadas}"


async def test_a_quebra_nao_persiste_depois_do_rollback(db: AsyncEngine) -> None:
    consulta = text(
        "SELECT count(*) FROM pg_policy WHERE polname = 'tenant_isolation' "
        "AND polrelid = 'conversations'::regclass"
    )
    async with db.connect() as conn:
        transacao = await conn.begin()
        await conn.execute(text("DROP POLICY tenant_isolation ON conversations"))
        assert (await conn.execute(consulta)).scalar_one() == 0
        await transacao.rollback()
        assert (await conn.execute(consulta)).scalar_one() == 1
