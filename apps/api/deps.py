"""Injeção de dependências da API (FastAPI `Depends`). Em testes, use `app.dependency_overrides`."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from redis.asyncio import Redis


def get_queue(request: Request) -> Any:
    """Pool do ARQ criado no lifespan (`app.state.queue`)."""
    return request.app.state.queue


def get_redis(request: Request) -> Redis:
    return request.app.state.redis  # type: ignore[no-any-return]
