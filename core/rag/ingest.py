"""Ingestão de documentos da empresa: hash, versionamento e substituição atômica (FR-011, FR-012)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from core.llm.ports import LLMClient, LLMError
from core.rag.chunking import EXTENSOES_SUPORTADAS, FormatoNaoSuportado, dividir, extrair_texto
from db.models import KnowledgeDocument, TenantKnowledge
from db.session import tenant_session

TAMANHO_MAXIMO_BYTES = 5 * 1024 * 1024
LOTE_EMBEDDING = 64

Status = Literal["ok", "inalterado", "sem_texto", "nao_suportado", "arquivo_grande", "falha"]
# Status que exigem atenção do operador e fazem a CLI sair com código 1.
STATUS_DE_FALHA: frozenset[Status] = frozenset({"falha", "sem_texto", "arquivo_grande"})


@dataclass(frozen=True)
class ResultadoIngestao:
    nome: str
    status: Status
    versao: int = 0
    trechos: int = 0
    tokens_embedding: int = 0
    custo_usd: Decimal = Decimal(0)
    erro: str | None = None


async def ingerir_documento(
    llm: LLMClient, *, tenant_id: uuid.UUID, nome_origem: str, conteudo: bytes
) -> ResultadoIngestao:
    """Indexa `conteudo`. A nova versão entra inteira ou a anterior permanece (uma transação).

    O conteúdo do arquivo é só dado: nunca é interpretado como instrução nem registrado em logs.
    """
    if len(conteudo) > TAMANHO_MAXIMO_BYTES:
        return ResultadoIngestao(nome_origem, "arquivo_grande")
    try:
        texto = extrair_texto(nome_origem, conteudo)
    except FormatoNaoSuportado:
        return ResultadoIngestao(nome_origem, "nao_suportado")
    except Exception as exc:  # noqa: BLE001  PDF corrompido ou criptografado
        return ResultadoIngestao(nome_origem, "falha", erro=f"leitura:{type(exc).__name__}")
    trechos = dividir(texto)
    if not trechos:
        return ResultadoIngestao(nome_origem, "sem_texto")

    content_hash = hashlib.sha256(conteudo).hexdigest()
    async with tenant_session(tenant_id) as s:
        existente = (
            await s.execute(
                select(KnowledgeDocument).where(KnowledgeDocument.nome_origem == nome_origem)
            )
        ).scalar_one_or_none()
        if existente is not None and existente.content_hash == content_hash:
            return ResultadoIngestao(
                nome_origem, "inalterado", versao=existente.versao, trechos=existente.num_trechos
            )

    vetores: list[list[float]] = []
    tokens = 0
    custo = Decimal(0)
    try:
        for i in range(0, len(trechos), LOTE_EMBEDDING):
            r = await llm.embed(textos=trechos[i : i + LOTE_EMBEDDING], tenant_id=tenant_id)
            vetores.extend(r.vetores)
            tokens += r.uso.tokens_entrada
            custo += r.uso.custo_usd
    except LLMError as exc:
        return ResultadoIngestao(nome_origem, "falha", erro=f"embedding:{exc.codigo}")

    try:
        async with tenant_session(tenant_id) as s:
            doc = (
                await s.execute(
                    select(KnowledgeDocument)
                    .where(KnowledgeDocument.nome_origem == nome_origem)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if doc is None:
                doc = KnowledgeDocument(
                    tenant_id=tenant_id, nome_origem=nome_origem, content_hash=content_hash
                )
                s.add(doc)
                doc.versao = 1
            else:
                await s.execute(
                    delete(TenantKnowledge).where(TenantKnowledge.documento_id == doc.id)
                )
                doc.content_hash = content_hash
                doc.versao += 1
            doc.num_trechos = len(trechos)
            await s.flush()
            s.add_all(
                TenantKnowledge(
                    tenant_id=tenant_id,
                    documento_id=doc.id,
                    documento_origem=nome_origem,
                    chunk_indice=i,
                    chunk_texto=texto_trecho,
                    embedding=vetor,
                )
                for i, (texto_trecho, vetor) in enumerate(zip(trechos, vetores, strict=True))
            )
            versao = doc.versao
    except IntegrityError:
        return ResultadoIngestao(nome_origem, "falha", erro="conflito_concorrente")
    return ResultadoIngestao(
        nome_origem,
        "ok",
        versao=versao,
        trechos=len(trechos),
        tokens_embedding=tokens,
        custo_usd=custo,
    )


async def listar_documentos(tenant_id: uuid.UUID) -> list[KnowledgeDocument]:
    async with tenant_session(tenant_id) as s:
        return list(
            (
                await s.execute(select(KnowledgeDocument).order_by(KnowledgeDocument.nome_origem))
            ).scalars()
        )


async def remover_documento(tenant_id: uuid.UUID, nome_origem: str) -> bool:
    """Remove o documento e seus trechos (CASCADE). Devolve `False` se não existir."""
    async with tenant_session(tenant_id) as s:
        resultado = await s.execute(
            delete(KnowledgeDocument).where(KnowledgeDocument.nome_origem == nome_origem)
        )
        return bool(resultado.rowcount)  # type: ignore[attr-defined]


__all__ = [
    "EXTENSOES_SUPORTADAS",
    "STATUS_DE_FALHA",
    "ResultadoIngestao",
    "ingerir_documento",
    "listar_documentos",
    "remover_documento",
]
