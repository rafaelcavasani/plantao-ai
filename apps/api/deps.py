"""Injeção de dependências da API (FastAPI `Depends`). Em testes, use `app.dependency_overrides`."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from redis.asyncio import Redis

from core.config import settings


def get_tenant_id() -> uuid.UUID:
    """Tenant do Sprint 2: sempre o piloto (`PILOT_TENANT_ID`). Resolução real por destino é do Sprint 3."""
    return settings.tenant_piloto()


def get_queue(request: Request) -> Any:
    """Pool do ARQ criado no lifespan (`app.state.queue`)."""
    return request.app.state.queue


def get_redis(request: Request) -> Redis:
    return request.app.state.redis  # type: ignore[no-any-return]
