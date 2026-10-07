"""Remessas de documentos enviadas pelo painel (spec 004, FR-041; research R-09).

A API guarda os arquivos no Redis por 1 hora e enfileira o job; o job indexa cada arquivo com a mesma função do
CLI (`ingerir_documento`) e grava o resultado por arquivo. O conteúdo dos arquivos é só dado: nunca é logado.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Final, Protocol

from core.llm.ports import LLMClient
from core.rag.ingest import ingerir_documento

__all__ = ["PREFIXO_REMESSA", "VALIDADE_REMESSA_S", "processar_remessa"]

PREFIXO_REMESSA: Final = "painel:remessa:"
VALIDADE_REMESSA_S: Final = 3600


class RedisLike(Protocol):
    async def get(self, chave: str) -> Any: ...
    async def set(self, chave: str, valor: Any, ex: int | None = None) -> Any: ...
    async def delete(self, *chaves: str) -> Any: ...


async def processar_remessa(redis: RedisLike, llm: LLMClient, remessa: str) -> dict[str, Any]:
    """Indexa os arquivos da remessa e grava `{arquivos: [{nome, status, trechos}]}`. Idempotente por nome."""
    base = PREFIXO_REMESSA + remessa
    bruto = await redis.get(base + ":meta")
    if bruto is None:
        return {"arquivos": []}  # remessa expirou
    meta = json.loads(bruto)
    tenant_id = uuid.UUID(meta["tenant_id"])
    resultados: list[dict[str, Any]] = []
    for i, nome in enumerate(meta["nomes"]):
        conteudo = await redis.get(f"{base}:arq:{i}")
        if conteudo is None:
            resultados.append({"nome": nome, "status": "falha", "trechos": 0})
            continue
        resultado = await ingerir_documento(
            llm, tenant_id=tenant_id, nome_origem=nome, conteudo=bytes(conteudo)
        )
        resultados.append({"nome": nome, "status": resultado.status, "trechos": resultado.trechos})
        await redis.delete(f"{base}:arq:{i}")
    final = {"arquivos": resultados}
    await redis.set(base + ":res", json.dumps(final), ex=VALIDADE_REMESSA_S)
    return final
