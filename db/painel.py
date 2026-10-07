"""Sessão do papel `plantao_painel` (spec 004, ADR-0006 e ADR-0008).

Esse papel só lê: tabelas agregadas do painel e metadados, por privilégio de coluna. Ele nunca enxerga o texto
das mensagens, o contato nem as credenciais, então um erro numa consulta falha com "permission denied" em vez
de vazar dado. Não define `app.tenant_id`: o painel lê entre empresas por política própria de leitura.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from core.config import settings


@lru_cache
def get_painel_engine() -> AsyncEngine:
    """Engine do papel `plantao_painel`. Em testes usa NullPool (cada teste tem seu event loop)."""
    if settings.env == "test":
        return create_async_engine(settings.database_painel_url, poolclass=NullPool)
    return create_async_engine(settings.database_painel_url, pool_pre_ping=True)


@asynccontextmanager
async def painel_session() -> AsyncIterator[AsyncSession]:
    """Sessão somente leitura do painel, dentro de uma transação que nunca grava."""
    factory = async_sessionmaker(get_painel_engine(), expire_on_commit=False)
    async with factory() as session, session.begin():
        yield session


async def fechar_painel_engine() -> None:
    await get_painel_engine().dispose()
