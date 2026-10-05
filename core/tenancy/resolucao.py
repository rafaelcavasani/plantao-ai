"""Resolução da empresa dona de uma mensagem recebida e montagem da conexão de envio.

- `resolver_conexao(instance)`: lê o diretório de roteamento (`channel_connections`, leitura aberta)
  sem contexto de tenant. É a única consulta feita antes de saber qual é a empresa.
- `autenticar_entrega(conexao, token)`: confere o token com o hash guardado **para aquela conexão**, em
  tempo constante. Instância desconhecida percorre o mesmo caminho com um hash falso, para que tempo e
  resposta não revelem quais instâncias existem.
- `carregar_conexao_canal(session, tenant_id, canal)`: monta `ConexaoCanal` com a chave de envio
  descriptografada, só em memória.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.ports.channel import ConexaoCanal
from core.security.crypto import get_cripto
from core.tenancy.conexoes import hash_segredo
from db.models import ChannelConnection, ChannelCredential
from db.session import get_session_factory, tenant_session

# Hash de um segredo que ninguém conhece; só serve para igualar o custo do caminho "desconhecida".
_HASH_FALSO: Final = hashlib.sha256(b"plantao-ai:instancia-desconhecida").hexdigest()


class ConexaoAusente(Exception):
    """A empresa não tem conexão (ou credencial) cadastrada para o canal."""


@dataclass(frozen=True)
class ConexaoRoteada:
    """Entrada do diretório de roteamento. Sem credenciais."""

    tenant_id: uuid.UUID
    connection_id: uuid.UUID
    canal: str
    provedor: str
    instance_name: str


async def resolver_conexao(
    instance: str, factory: async_sessionmaker[AsyncSession] | None = None
) -> ConexaoRoteada | None:
    """Empresa dona da instância, ou `None` se ela não existir."""
    if not instance:
        return None
    factory = factory or get_session_factory()
    async with factory() as session:
        linha = (
            await session.execute(
                select(
                    ChannelConnection.tenant_id,
                    ChannelConnection.id,
                    ChannelConnection.canal,
                    ChannelConnection.provedor,
                    ChannelConnection.instance_name,
                ).where(ChannelConnection.instance_name == instance)
            )
        ).one_or_none()
    if linha is None:
        return None
    return ConexaoRoteada(*linha)


async def autenticar_entrega(conexao: ConexaoRoteada | None, token: str | None) -> bool:
    """`True` só se `token` for o segredo de entrega da conexão encontrada."""
    recebido = hash_segredo(token or "")
    esperado = _HASH_FALSO
    if conexao is not None:
        async with tenant_session(conexao.tenant_id) as session:
            guardado = (
                await session.execute(
                    select(ChannelCredential.webhook_secret_hash).where(
                        ChannelCredential.connection_id == conexao.connection_id
                    )
                )
            ).scalar_one_or_none()
        esperado = guardado or _HASH_FALSO
    iguais = hmac.compare_digest(recebido, esperado)
    return iguais and conexao is not None and esperado != _HASH_FALSO


async def carregar_conexao_canal(
    session: AsyncSession, tenant_id: uuid.UUID, canal: str = "whatsapp"
) -> ConexaoCanal:
    """Conexão de envio da empresa, com a chave descriptografada. `session` é da própria empresa."""
    linha = (
        await session.execute(
            select(
                ChannelConnection.provedor,
                ChannelConnection.instance_name,
                ChannelCredential.api_key_enc,
            )
            .join(ChannelCredential, ChannelCredential.connection_id == ChannelConnection.id)
            .where(ChannelConnection.tenant_id == tenant_id, ChannelConnection.canal == canal)
        )
    ).one_or_none()
    if linha is None:
        raise ConexaoAusente(f"sem conexao de {canal} para a empresa")
    provedor, instance_name, api_key_enc = linha
    return ConexaoCanal(
        tenant_id=tenant_id,
        canal=canal,
        provedor=provedor,
        instance_name=instance_name,
        api_key=get_cripto().decrypt(api_key_enc),
    )
