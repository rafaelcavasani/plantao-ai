"""Busca de trechos por similaridade de cosseno, sempre filtrada por tenant (R-07)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from core.llm.ports import LLMClient
from db.models import TenantKnowledge
from db.session import tenant_session


@dataclass(frozen=True)
class Trecho:
    id: str
    texto: str
    documento: str
    similaridade: float


async def buscar_trechos(
    llm: LLMClient,
    *,
    tenant_id: uuid.UUID,
    pergunta: str,
    top_k: int = 4,
    min_similarity: float = 0.30,
    conversation_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
) -> list[Trecho]:
    """Até `top_k` trechos do tenant com similaridade >= `min_similarity`, do mais ao menos similar.

    Levanta `LLMError` se o embedding da pergunta falhar. Base vazia ou sem trecho relevante devolve `[]`.
    """
    resultado = await llm.embed(
        textos=[pergunta],
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message_id=message_id,
    )
    distancia = TenantKnowledge.embedding.cosine_distance(resultado.vetores[0])
    async with tenant_session(tenant_id) as session:
        linhas = (
            await session.execute(
                select(
                    TenantKnowledge.id,
                    TenantKnowledge.chunk_texto,
                    TenantKnowledge.documento_origem,
                    (1 - distancia).label("similaridade"),
                )
                .where(TenantKnowledge.tenant_id == tenant_id, distancia <= 1 - min_similarity)
                .order_by(distancia)
                .limit(top_k)
            )
        ).all()
    return [
        Trecho(str(r.id), r.chunk_texto, r.documento_origem, float(r.similaridade)) for r in linhas
    ]
