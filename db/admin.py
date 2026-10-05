"""Sessão do papel administrativo (`DATABASE_ADMIN_URL`), usada só por `scripts/` (research R-16).

O papel administrativo ignora RLS: serve a operações entre empresas (criar empresa, mudar estado, listar).
Dados de uma empresa continuam passando por `tenant_session`. Nenhum módulo de `apps/` pode importar este.
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
def get_admin_engine() -> AsyncEngine:
    """Engine administrativo. `NullPool`: comandos de operador são curtos e cada `asyncio.run` tem seu loop."""
    return create_async_engine(settings.database_admin_url, poolclass=NullPool)


@asynccontextmanager
async def admin_session() -> AsyncIterator[AsyncSession]:
    """Sessão administrativa com transação aberta; commit ao sair sem erro, rollback em exceção."""
    factory = async_sessionmaker(get_admin_engine(), expire_on_commit=False)
    async with factory() as session, session.begin():
        yield session


async def fechar_admin_engine() -> None:
    await get_admin_engine().dispose()
