"""Engine e sessão assíncrona do SQLAlchemy.

Toda leitura e escrita de dados de tenant passa por `tenant_session`, que define `app.tenant_id` na
transação para que o Row-Level Security do Postgres filtre as linhas (princípio III).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from core.config import settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Engine do papel `plantao_app`. Em testes usa NullPool (cada teste tem seu event loop)."""
    if settings.env == "test":
        return create_async_engine(settings.database_url, poolclass=NullPool)
    return create_async_engine(
        settings.database_url, echo=settings.env == "development", pool_pre_ping=True
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@asynccontextmanager
async def tenant_session(
    tenant_id: uuid.UUID, factory: async_sessionmaker[AsyncSession] | None = None
) -> AsyncIterator[AsyncSession]:
    """Sessão com transação aberta e `app.tenant_id` definido (válido só nesta transação).

    Faz commit ao sair sem erro e rollback em exceção. Sem tenant definido, o RLS devolve zero linhas.
    """
    factory = factory or get_session_factory()
    async with factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
        )
        yield session


async def fechar_engine() -> None:
    await get_engine().dispose()
