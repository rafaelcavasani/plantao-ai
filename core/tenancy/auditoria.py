"""Trilha de auditoria por campo (FR-029).

Escreve na sessão recebida, sem commit: a linha de auditoria entra na mesma transação da mudança e some
junto se ela for desfeita. Credenciais nunca são gravadas; entram como `"<atualizada>"`.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLog

MARCA_CREDENCIAL: Final = "<atualizada>"
CAMPOS_SECRETOS: Final = frozenset({"credencial", "api_key", "webhook_secret"})


async def registrar_mudanca(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    entidade: str,
    campo: str,
    anterior: Any,
    novo: Any,
    operador: str,
) -> None:
    """Acrescenta uma linha de auditoria (um campo) à transação da `session`."""
    if campo in CAMPOS_SECRETOS:
        anterior = None if anterior is None else MARCA_CREDENCIAL
        novo = None if novo is None else MARCA_CREDENCIAL
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            entidade=entidade,
            campo=campo,
            valor_anterior=anterior,
            valor_novo=novo,
            operador=operador,
        )
    )
    await session.flush()
