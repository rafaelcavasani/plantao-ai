"""Segurança HTTP do painel: `Origin`, limite de taxa por operador e cabeçalhos (research R-07)."""

from __future__ import annotations

import time
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Request
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from apps.api.admin.auth import exigir_operacao
from apps.api.admin.schemas import ErroAdmin, Operador
from apps.api.deps import get_redis
from core.config import settings

METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'"
)
CABECALHOS_PAINEL = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


async def verificar_origem(request: Request) -> None:
    """Rotas que alteram estado só aceitam `Origin` igual ao host do painel (barra requisição forjada)."""
    if request.method in METODOS_SEGUROS:
        return
    origem = request.headers.get("origin")
    host = request.headers.get("host")
    if not origem or not host or urlsplit(origem).netloc != host:
        raise ErroAdmin(403, "origem_invalida", "Origem da requisição não permitida.")


async def proteger_escrita(
    operador: Annotated[Operador, Depends(exigir_operacao)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> Operador:
    """Papel `operacao` + limite de `PAINEL_ESCRITA_POR_MINUTO` escritas por operador e minuto."""
    chave = f"painel:rl:{operador.email}:{int(time.time() // 60)}"
    total = await redis.incr(chave)
    if total == 1:
        await redis.expire(chave, 90)
    if int(total) > settings.painel_escrita_por_minuto:
        raise ErroAdmin(
            429,
            "limite_excedido",
            "Muitas alterações em pouco tempo. Aguarde um instante.",
            cabecalhos={"Retry-After": "60"},
        )
    return operador


Escritor = Annotated[Operador, Depends(proteger_escrita)]


class CabecalhosDeSeguranca(BaseHTTPMiddleware):
    """Cabeçalhos do painel (CSP estrita) e `no-store` nas respostas de dados da API de operação."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        resposta = await call_next(request)
        caminho = request.url.path
        if caminho.startswith(("/painel", "/admin")) and settings.env not in (
            "development",
            "test",
        ):
            resposta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if caminho.startswith("/painel"):
            for nome, valor in CABECALHOS_PAINEL.items():
                resposta.headers[nome] = valor
        elif caminho.startswith("/admin"):
            resposta.headers["Cache-Control"] = "no-store"
            resposta.headers["X-Content-Type-Options"] = "nosniff"
        return resposta


class PainelEstatico(StaticFiles):
    """Arquivos do front-end: sem listagem de pasta e sem cache longo durante a evolução do painel."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        resposta = await super().get_response(path, scope)
        resposta.headers.setdefault("Cache-Control", "no-cache")
        return resposta
