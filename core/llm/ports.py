"""Portas e tipos da camada de LLM (contrato em specs/001-router-support-agent/contracts/llm-contracts.md)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol


class Finalidade(StrEnum):
    ROTEADOR = "roteador"
    SUPORTE = "suporte"
    EMBEDDING = "embedding"


class LLMError(Exception):
    """Falha de LLM ou embedding após timeout, retry ou resposta inválida do gateway."""

    def __init__(self, codigo: str) -> None:
        super().__init__(codigo)
        self.codigo = codigo


class SaidaInvalida(Exception):
    """A saída do modelo não obedece ao schema esperado (JSON inválido, campo fora do enum etc.)."""


@dataclass(frozen=True)
class Uso:
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_usd: Decimal = Decimal(0)
    latencia_ms: int = 0


@dataclass(frozen=True)
class LLMResult:
    texto: str
    modelo: str
    uso: Uso


@dataclass(frozen=True)
class EmbedResult:
    vetores: list[list[float]]
    modelo: str
    uso: Uso


@dataclass(frozen=True)
class ChamadaLLM:
    """Registro de uma chamada (vira uma linha em `llm_calls`)."""

    tenant_id: uuid.UUID
    finalidade: Finalidade
    modelo: str
    sucesso: bool
    uso: Uso
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    erro: str | None = None


Mensagem = dict[str, str]


class LLMClient(Protocol):
    async def complete_json(
        self,
        *,
        finalidade: Finalidade,
        modelo: str,
        mensagens: Sequence[Mensagem],
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID | None = None,
        message_id: uuid.UUID | None = None,
    ) -> LLMResult:
        """Chamada de chat que devolve JSON bruto. Levanta `LLMError`."""
        ...

    async def embed(
        self,
        *,
        textos: Sequence[str],
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID | None = None,
        message_id: uuid.UUID | None = None,
    ) -> EmbedResult:
        """Embeddings de 1536 dimensões. Levanta `LLMError`."""
        ...
