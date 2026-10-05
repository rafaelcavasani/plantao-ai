"""Auxiliares de teste: respostas JSON roteirizadas e base de conhecimento no banco."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from core.rag.retrieve import Trecho
from db.models import KnowledgeDocument, TenantKnowledge
from tests.fakes.embeddings import embed_falso


def json_roteador(
    intencao: str = "suporte", confianca: float = 0.95, secundarias: Sequence[str] = ()
) -> str:
    return json.dumps(
        {"intencao": intencao, "confianca": confianca, "intencoes_secundarias": list(secundarias)}
    )


def json_suporte(
    resposta: str = "Atendemos aos sábados das 8h às 12h.",
    confianca: float = 0.95,
    trechos: Sequence[str] = (),
    responde: bool = True,
) -> str:
    return json.dumps(
        {
            "responde": responde,
            "confianca": confianca,
            "resposta": resposta,
            "trechos_usados": list(trechos),
        }
    )


def trecho(texto: str, similaridade: float = 0.9, id: str | None = None) -> Trecho:
    return Trecho(id or str(uuid.uuid4()), texto, "faq.md", similaridade)


def buscar_fixo(trechos: Sequence[Trecho]) -> Callable[..., Awaitable[list[Trecho]]]:
    """`buscar` do grafo que devolve sempre os mesmos trechos (sem banco nem embedding)."""

    async def _buscar(llm: object, **_: object) -> list[Trecho]:
        return list(trechos)

    return _buscar


async def inserir_conhecimento(
    engine: AsyncEngine, tenant_id: uuid.UUID, documentos: dict[str, list[str]]
) -> dict[str, list[uuid.UUID]]:
    """Grava documentos e trechos (embedding falso) como admin; devolve ids dos trechos por documento."""
    ids: dict[str, list[uuid.UUID]] = {}
    async with AsyncSession(engine, expire_on_commit=False) as session:
        for nome, trechos in documentos.items():
            doc = KnowledgeDocument(
                tenant_id=tenant_id, nome_origem=nome, content_hash=nome, num_trechos=len(trechos)
            )
            session.add(doc)
            await session.flush()
            ids[nome] = []
            for i, texto in enumerate(trechos):
                registro = TenantKnowledge(
                    tenant_id=tenant_id,
                    documento_id=doc.id,
                    documento_origem=nome,
                    chunk_indice=i,
                    chunk_texto=texto,
                    embedding=embed_falso(texto),
                )
                session.add(registro)
                await session.flush()
                ids[nome].append(registro.id)
        await session.commit()
    return ids
