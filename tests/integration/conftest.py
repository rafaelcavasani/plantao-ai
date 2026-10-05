"""Fixtures dos testes de integração que passam pelo webhook (API, fila falsa e Redis falso)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import AsyncEngine

from apps.api.deps import get_queue, get_redis
from apps.api.main import app
from tests.fakes.channel import FakeQueue


@pytest.fixture
def fila() -> FakeQueue:
    return FakeQueue()


@pytest_asyncio.fixture
async def redis() -> AsyncIterator[FakeAsyncRedis]:
    r = FakeAsyncRedis()
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def cliente(
    fila: FakeQueue, redis: FakeAsyncRedis, db: AsyncEngine
) -> AsyncIterator[httpx.AsyncClient]:
    app.dependency_overrides[get_queue] = lambda: fila
    app.dependency_overrides[get_redis] = lambda: redis
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
