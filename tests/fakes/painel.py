"""Apoio dos testes do painel: cliente HTTP da API de operação com sessão, Redis e fila falsos (spec 004)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from fakeredis import FakeAsyncRedis

from apps.api.admin.auth import COOKIE, SessaoStore
from tests.fakes.channel import FakeChannel, FakeQueue

BASE = "http://t"
OPERADOR = "operador@exemplo.com"
LEITOR = "leitor@exemplo.com"


@dataclass
class AdminApi:
    """`cliente` fala com a app; `redis` e `fila` são os falsos injetados; `cabecalhos` já traz sessão e Origin."""

    cliente: httpx.AsyncClient
    redis: FakeAsyncRedis
    fila: FakeQueue
    canal: FakeChannel

    async def cabecalhos(
        self, email: str = OPERADOR, *, origem: str | None = BASE
    ) -> dict[str, str]:
        papel = "operacao" if email == OPERADOR else "leitura"
        token = await SessaoStore(self.redis).criar(email, papel)  # type: ignore[arg-type]
        cab = {"Cookie": f"{COOKIE}={token}"}
        if origem is not None:
            cab["Origin"] = origem
        return cab

    async def get(self, caminho: str, *, email: str = OPERADOR, **kw: Any) -> httpx.Response:
        return await self.cliente.get(caminho, headers=await self.cabecalhos(email), **kw)

    async def post(
        self, caminho: str, *, email: str = OPERADOR, origem: str | None = BASE, **kw: Any
    ) -> httpx.Response:
        return await self.cliente.post(
            caminho, headers=await self.cabecalhos(email, origem=origem), **kw
        )

    async def delete(self, caminho: str, *, email: str = OPERADOR, **kw: Any) -> httpx.Response:
        return await self.cliente.delete(caminho, headers=await self.cabecalhos(email), **kw)

    async def put(self, caminho: str, *, email: str = OPERADOR, **kw: Any) -> httpx.Response:
        return await self.cliente.put(caminho, headers=await self.cabecalhos(email), **kw)

    async def patch(self, caminho: str, *, email: str = OPERADOR, **kw: Any) -> httpx.Response:
        return await self.cliente.patch(caminho, headers=await self.cabecalhos(email), **kw)


CHAVES_PROIBIDAS = (
    "conteudo",
    "contato",
    "segredo",
    "chave",
    "hash",
    "external_id",
    "cookie",
    "senha",
)


def chaves_proibidas(valor: Any, caminho: str = "") -> list[str]:
    """Caminhos de qualquer chave JSON proibida (texto, contato, segredo...). Lista vazia = limpo."""
    achados: list[str] = []
    if isinstance(valor, dict):
        for chave, sub in valor.items():
            nome = str(chave).lower()
            if any(p in nome for p in CHAVES_PROIBIDAS) and nome not in PERMITIDAS:
                achados.append(f"{caminho}.{chave}")
            achados += chaves_proibidas(sub, f"{caminho}.{chave}")
    elif isinstance(valor, list):
        for i, sub in enumerate(valor):
            achados += chaves_proibidas(sub, f"{caminho}[{i}]")
    return achados


# Nomes de campo legítimos que contêm um termo proibido como parte de outra palavra.
PERMITIDAS = frozenset({"credenciais", "chave"})  # `chave` = chave do plano em /admin/planos
