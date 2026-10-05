"""Cadastro de conexão de canal e credenciais (FR-002, FR-005)."""

import hashlib
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from core.security.crypto import get_cripto
from core.tenancy import ConexaoCadastrada, ConexaoEmUso, SegredoInvalido, cadastrar_conexao
from db.models import AuditLog, ChannelConnection, ChannelCredential
from db.session import tenant_session

pytestmark = pytest.mark.integration

SEGREDO = "s" * 40
CHAVE = "chave-de-envio-da-empresa"


async def _cadastrar(
    tenant_id: uuid.UUID,
    instance: str = "inst-a",
    segredo: str = SEGREDO,
    chave: str = CHAVE,
    operador: str = "ana",
) -> ConexaoCadastrada:
    async with tenant_session(tenant_id) as s:
        return await cadastrar_conexao(
            s,
            tenant_id,
            instance_name=instance,
            webhook_secret=segredo,
            api_key=chave,
            operador=operador,
        )


async def _auditoria(tenant_id: uuid.UUID) -> list[AuditLog]:
    async with tenant_session(tenant_id) as s:
        return list(
            (await s.execute(select(AuditLog).order_by(AuditLog.criado_em, AuditLog.campo)))
            .scalars()
            .all()
        )


async def test_grava_hash_do_segredo_e_chave_cifrada(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    await _cadastrar(tenant_a)

    async with tenant_session(tenant_a) as s:
        cred = (await s.execute(select(ChannelCredential))).scalar_one()
    assert cred.webhook_secret_hash == hashlib.sha256(SEGREDO.encode()).hexdigest()
    assert len(cred.webhook_secret_hash) == 64
    assert SEGREDO not in cred.webhook_secret_hash
    assert cred.api_key_enc != CHAVE
    assert CHAVE not in cred.api_key_enc
    assert get_cripto().decrypt(cred.api_key_enc) == CHAVE


async def test_instance_em_uso_por_outra_empresa_e_recusada(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await _cadastrar(tenant_a, instance="numero-compartilhado")

    with pytest.raises(ConexaoEmUso) as info:
        await _cadastrar(tenant_b, instance="numero-compartilhado")
    assert str(tenant_a) not in str(info.value)

    async with tenant_session(tenant_b) as s:
        # B só enxerga o diretório; nada novo foi gravado para ela
        donos = (await s.execute(select(ChannelConnection.tenant_id))).scalars().all()
        assert donos == [tenant_a]
        assert (await s.execute(select(ChannelCredential))).scalars().all() == []
    assert await _auditoria(tenant_b) == []


async def test_segundo_canal_igual_na_mesma_empresa_e_recusado(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _cadastrar(tenant_a, instance="inst-1")
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_a) as s:
            s.add(
                ChannelConnection(
                    tenant_id=tenant_a,
                    canal="whatsapp",
                    provedor="evolution",
                    instance_name="inst-2",
                )
            )


@pytest.mark.parametrize("segredo", ["", "curto", "x" * 31])
async def test_segredo_curto_e_recusado(db: AsyncEngine, tenant_a: uuid.UUID, segredo: str) -> None:
    with pytest.raises(SegredoInvalido) as info:
        await _cadastrar(tenant_a, segredo=segredo)
    assert segredo not in str(info.value) or segredo == ""
    async with tenant_session(tenant_a) as s:
        assert (await s.execute(select(ChannelConnection))).scalars().all() == []


async def test_repetir_com_o_mesmo_valor_nao_audita(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    primeira = await _cadastrar(tenant_a)
    depois_da_primeira = len(await _auditoria(tenant_a))
    assert depois_da_primeira >= 1  # criação audita instância e credencial

    segunda = await _cadastrar(tenant_a)

    assert len(await _auditoria(tenant_a)) == depois_da_primeira
    assert primeira.connection_id == segunda.connection_id
    assert segunda.criada is False and segunda.alterada is False
    async with tenant_session(tenant_a) as s:
        assert len((await s.execute(select(ChannelConnection))).scalars().all()) == 1


async def test_valor_novo_audita_credencial_sem_o_valor(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _cadastrar(tenant_a)
    antes = len(await _auditoria(tenant_a))

    resultado = await _cadastrar(tenant_a, segredo="n" * 40, chave="outra-chave-de-envio")

    assert resultado.alterada is True
    novas = (await _auditoria(tenant_a))[antes:]
    assert [(a.entidade, a.campo, a.valor_novo, a.operador) for a in novas] == [
        ("conexao", "credencial", "<atualizada>", "ana")
    ]
    async with tenant_session(tenant_a) as s:
        cred = (await s.execute(select(ChannelCredential))).scalar_one()
    assert cred.webhook_secret_hash == hashlib.sha256(("n" * 40).encode()).hexdigest()
    assert get_cripto().decrypt(cred.api_key_enc) == "outra-chave-de-envio"
    for linha in await _auditoria(tenant_a):
        assert SEGREDO not in repr(linha.valor_novo) + repr(linha.valor_anterior)
        assert CHAVE not in repr(linha.valor_novo) + repr(linha.valor_anterior)


async def test_empresa_nao_le_credenciais_de_outra(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await _cadastrar(tenant_a, instance="inst-a")
    await _cadastrar(tenant_b, instance="inst-b", segredo="b" * 40, chave="chave-b")

    async with tenant_session(tenant_b) as s:
        creds = (await s.execute(select(ChannelCredential))).scalars().all()
    assert [c.tenant_id for c in creds] == [tenant_b]
