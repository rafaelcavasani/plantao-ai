"""Cadastro da conexão de canal de uma empresa e das credenciais dela (FR-002, FR-005).

O segredo de entrega fica só como hash `sha256` (basta para conferir o token recebido) e a chave de envio,
cifrada com Fernet (precisa ser recuperada para enviar). Nada disso aparece em log, erro ou auditoria.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security.crypto import get_cripto
from core.tenancy.auditoria import MARCA_CREDENCIAL, registrar_mudanca
from db.models import ChannelConnection, ChannelCredential

TAMANHO_MINIMO_SEGREDO: Final = 32


class ConexaoEmUso(Exception):
    """A instância do canal já pertence a outra empresa."""


class SegredoInvalido(ValueError):
    """Segredo de entrega curto demais ou chave de envio vazia. A mensagem nunca traz o valor."""


@dataclass(frozen=True)
class ConexaoCadastrada:
    connection_id: uuid.UUID
    criada: bool
    alterada: bool


def hash_segredo(segredo: str) -> str:
    return hashlib.sha256(segredo.encode()).hexdigest()


async def cadastrar_conexao(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    instance_name: str,
    webhook_secret: str,
    api_key: str,
    operador: str,
    canal: str = "whatsapp",
    provedor: str = "evolution",
) -> ConexaoCadastrada:
    """Cria ou atualiza a conexão da empresa. Idempotente: valores iguais não geram auditoria.

    `session` deve ser uma `tenant_session` da própria empresa. Não faz commit.
    """
    if len(webhook_secret) < TAMANHO_MINIMO_SEGREDO:
        raise SegredoInvalido(
            f"O segredo de entrega precisa ter pelo menos {TAMANHO_MINIMO_SEGREDO} caracteres."
        )
    if not api_key:
        raise SegredoInvalido("A chave de envio do canal esta vazia.")
    if not instance_name:
        raise ValueError("instance_name vazio.")

    dona = (
        await session.execute(
            select(ChannelConnection.tenant_id).where(
                ChannelConnection.instance_name == instance_name
            )
        )
    ).scalar_one_or_none()
    if dona is not None and dona != tenant_id:
        raise ConexaoEmUso(f"A instancia '{instance_name}' ja esta em uso por outra empresa.")

    cripto = get_cripto()
    conexao = (
        await session.execute(
            select(ChannelConnection).where(
                ChannelConnection.tenant_id == tenant_id, ChannelConnection.canal == canal
            )
        )
    ).scalar_one_or_none()

    if conexao is None:
        conexao = ChannelConnection(
            tenant_id=tenant_id, canal=canal, provedor=provedor, instance_name=instance_name
        )
        session.add(conexao)
        await session.flush()
        session.add(
            ChannelCredential(
                connection_id=conexao.id,
                tenant_id=tenant_id,
                webhook_secret_hash=hash_segredo(webhook_secret),
                api_key_enc=cripto.encrypt(api_key),
            )
        )
        await session.flush()
        await registrar_mudanca(
            session, tenant_id, "conexao", "instance_name", None, instance_name, operador
        )
        await registrar_mudanca(
            session, tenant_id, "conexao", "credencial", None, MARCA_CREDENCIAL, operador
        )
        return ConexaoCadastrada(conexao.id, criada=True, alterada=True)

    alterada = False
    if conexao.instance_name != instance_name:
        await registrar_mudanca(
            session,
            tenant_id,
            "conexao",
            "instance_name",
            conexao.instance_name,
            instance_name,
            operador,
        )
        conexao.instance_name = instance_name
        alterada = True
    if conexao.provedor != provedor:
        conexao.provedor = provedor
        alterada = True

    cred = await session.get(ChannelCredential, conexao.id)
    novo_hash = hash_segredo(webhook_secret)
    if cred is None:
        session.add(
            ChannelCredential(
                connection_id=conexao.id,
                tenant_id=tenant_id,
                webhook_secret_hash=novo_hash,
                api_key_enc=cripto.encrypt(api_key),
            )
        )
        await registrar_mudanca(
            session, tenant_id, "conexao", "credencial", None, MARCA_CREDENCIAL, operador
        )
        alterada = True
    elif cred.webhook_secret_hash != novo_hash or cripto.decrypt(cred.api_key_enc) != api_key:
        cred.webhook_secret_hash = novo_hash
        cred.api_key_enc = cripto.encrypt(api_key)
        await registrar_mudanca(
            session,
            tenant_id,
            "conexao",
            "credencial",
            MARCA_CREDENCIAL,
            MARCA_CREDENCIAL,
            operador,
        )
        alterada = True

    await session.flush()
    return ConexaoCadastrada(conexao.id, criada=False, alterada=alterada)
