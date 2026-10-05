"""Limite de mensagens por minuto por tenant, em Redis (FR-016)."""

from __future__ import annotations

import time
import uuid

from redis.asyncio import Redis


async def excedeu_limite(redis: Redis, tenant_id: uuid.UUID, limite_por_minuto: int) -> bool:
    """Conta a mensagem no minuto corrente e informa se o tenant passou do limite."""
    chave = f"rl:{tenant_id}:{int(time.time() // 60)}"
    total = await redis.incr(chave)
    if total == 1:
        await redis.expire(chave, 90)
    return int(total) > limite_por_minuto
