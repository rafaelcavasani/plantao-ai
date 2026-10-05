"""Resolução da empresa pela conexão do canal (FR-001, FR-003, research R-01 e R-02)."""

import hashlib
import hmac
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from core.ports.channel import ConexaoCanal
from core.tenancy import resolucao
from core.tenancy.resolucao import (
    ConexaoAusente,
    autenticar_entrega,
    carregar_conexao_canal,
    resolver_conexao,
)
from db.session import tenant_session
from tests.conftest import criar_conexao

pytestmark = pytest.mark.integration


async def test_resolve_a_empresa_pela_instancia_sem_contexto_de_tenant(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    a = await criar_conexao(db, tenant_a, instance_name="inst-a")
    b = await criar_conexao(db, tenant_b, instance_name="inst-b")

    achada_a = await resolver_conexao("inst-a")
    achada_b = await resolver_conexao("inst-b")

    assert achada_a is not None and achada_a.tenant_id == tenant_a
    assert achada_a.connection_id == a.connection_id
    assert achada_b is not None and achada_b.tenant_id == tenant_b
    assert (achada_a.canal, achada_a.provedor, achada_a.instance_name) == (
        "whatsapp",
        "evolution",
        "inst-a",
    )
    assert b.connection_id == achada_b.connection_id


@pytest.mark.parametrize("instancia", ["", "nao-existe", "INST-A", "inst-a "])
async def test_instancia_desconhecida_devolve_none(
    db: AsyncEngine, tenant_a: uuid.UUID, instancia: str
) -> None:
    await criar_conexao(db, tenant_a, instance_name="inst-a")
    assert await resolver_conexao(instancia) is None


async def test_autentica_com_o_segredo_da_propria_conexao(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    a = await criar_conexao(db, tenant_a, instance_name="inst-a")
    b = await criar_conexao(db, tenant_b, instance_name="inst-b")
    conexao_a = await resolver_conexao("inst-a")

    assert await autenticar_entrega(conexao_a, a.webhook_secret) is True
    assert (
        await autenticar_entrega(conexao_a, b.webhook_secret) is False
    )  # segredo de outra empresa
    assert await autenticar_entrega(conexao_a, "errado") is False
    assert await autenticar_entrega(conexao_a, "") is False
    assert await autenticar_entrega(conexao_a, None) is False


async def test_instancia_desconhecida_percorre_o_mesmo_caminho_de_custo(
    db: AsyncEngine, tenant_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = await criar_conexao(db, tenant_a, instance_name="inst-a")
    chamadas: list[int] = []
    original = hmac.compare_digest

    def espiao(x: str | bytes, y: str | bytes) -> bool:
        chamadas.append(1)
        return original(x, y)

    monkeypatch.setattr(resolucao.hmac, "compare_digest", espiao)

    assert await autenticar_entrega(None, "qualquer-token") is False
    assert len(chamadas) == 1
    assert await autenticar_entrega(await resolver_conexao("inst-a"), a.webhook_secret) is True
    assert len(chamadas) == 2


async def test_conexao_sem_credencial_nao_autentica(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    from sqlalchemy import text

    c = await criar_conexao(db, tenant_a, instance_name="inst-a")
    async with db.begin() as conn:
        await conn.execute(text("DELETE FROM channel_credentials"))
    assert await autenticar_entrega(await resolver_conexao("inst-a"), c.webhook_secret) is False


async def test_carrega_a_conexao_com_a_chave_descriptografada(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    c = await criar_conexao(db, tenant_a, instance_name="inst-a", api_key="chave-em-claro-a")

    async with tenant_session(tenant_a) as s:
        conexao = await carregar_conexao_canal(s, tenant_a, "whatsapp")

    assert isinstance(conexao, ConexaoCanal)
    assert conexao.api_key == "chave-em-claro-a" == c.api_key
    assert (conexao.tenant_id, conexao.instance_name, conexao.provedor) == (
        tenant_a,
        "inst-a",
        "evolution",
    )
    assert "chave-em-claro-a" not in repr(conexao)


async def test_empresa_sem_conexao_levanta_erro_tipado(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await criar_conexao(db, tenant_a, instance_name="inst-a")
    async with tenant_session(tenant_b) as s:
        with pytest.raises(ConexaoAusente):
            await carregar_conexao_canal(s, tenant_b, "whatsapp")


async def test_empresa_sem_credencial_levanta_erro_tipado(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    from sqlalchemy import text

    await criar_conexao(db, tenant_a, instance_name="inst-a")
    async with db.begin() as conn:
        await conn.execute(text("DELETE FROM channel_credentials"))
    async with tenant_session(tenant_a) as s:
        with pytest.raises(ConexaoAusente):
            await carregar_conexao_canal(s, tenant_a, "whatsapp")


def test_hash_do_segredo_e_sha256() -> None:
    from core.tenancy import hash_segredo

    assert hash_segredo("abc") == hashlib.sha256(b"abc").hexdigest()
