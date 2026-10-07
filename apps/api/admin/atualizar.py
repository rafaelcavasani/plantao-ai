"""`POST /admin/atualizar`: pede uma nova agregação (FR-042, research R-11).

Qualquer operador autenticado pode atualizar (não altera dado de empresa). No máximo uma por operador a cada
30 segundos e uma execução por vez (trava de 20 s).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from redis.asyncio import Redis

from apps.api.admin.auth import OperadorAtual
from apps.api.admin.schemas import ErroAdmin
from apps.api.deps import get_queue, get_redis
from core.painel import consultas

router = APIRouter()

TRAVA = "painel:atualizar:lock"
TRAVA_SEGUNDOS = 20
POR_OPERADOR_SEGUNDOS = 30


@router.post("/atualizar", status_code=202)
async def atualizar(
    operador: OperadorAtual,
    redis: Annotated[Redis, Depends(get_redis)],
    fila: Annotated[Any, Depends(get_queue)],
) -> dict[str, Any]:
    if not await redis.set(
        f"painel:atualizar:{operador.email}", "1", ex=POR_OPERADOR_SEGUNDOS, nx=True
    ):
        raise ErroAdmin(
            429,
            "limite_excedido",
            "Aguarde alguns segundos antes de atualizar de novo.",
            cabecalhos={"Retry-After": str(POR_OPERADOR_SEGUNDOS)},
        )
    if await redis.set(TRAVA, "1", ex=TRAVA_SEGUNDOS, nx=True):
        await fila.enqueue_job("agregar_painel")
    saude = await consultas.saude_dos_dados()
    return {"enfileirado": True, "atualizado_em": saude["atualizado_em"]}
