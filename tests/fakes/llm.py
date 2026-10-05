"""`FakeLLMClient`: LLM roteirizado, sem rede nem banco."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from core.llm.ports import EmbedResult, Finalidade, LLMError, LLMResult, Mensagem, Uso
from tests.fakes.embeddings import embed_falso


class FakeLLMClient:
    """Devolve, na ordem, as respostas de `respostas`. Um item `Exception` é levantado.

    `respostas` pode ser uma lista (consumida em ordem, por qualquer finalidade) ou um dict
    `{Finalidade: [..]}` (fila separada por finalidade).
    """

    def __init__(
        self,
        respostas: Sequence[str | Exception]
        | dict[Finalidade, Sequence[str | Exception]]
        | None = None,
        *,
        falhar_embedding: bool = False,
    ) -> None:
        if isinstance(respostas, dict):
            self._por_finalidade: dict[Finalidade, list[str | Exception]] | None = {
                k: list(v) for k, v in respostas.items()
            }
            self._fila: list[str | Exception] = []
        else:
            self._por_finalidade = None
            self._fila = list(respostas or [])
        self.falhar_embedding = falhar_embedding
        self.chamadas: list[dict[str, Any]] = []
        self.embeds: list[list[str]] = []

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
        self.chamadas.append(
            {"finalidade": finalidade, "modelo": modelo, "mensagens": list(mensagens)}
        )
        fila = (
            self._por_finalidade.get(finalidade, [])
            if self._por_finalidade is not None
            else self._fila
        )
        if not fila:
            raise AssertionError(f"FakeLLMClient sem resposta roteirizada para {finalidade}")
        item = fila.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult(texto=item, modelo=modelo, uso=Uso(100, 20, Decimal("0.0001"), 5))

    async def embed(
        self,
        *,
        textos: Sequence[str],
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID | None = None,
        message_id: uuid.UUID | None = None,
    ) -> EmbedResult:
        self.embeds.append(list(textos))
        if self.falhar_embedding:
            raise LLMError("timeout")
        return EmbedResult(
            vetores=[embed_falso(t) for t in textos],
            modelo="fake-embedding",
            uso=Uso(10 * len(textos)),
        )

    @property
    def finalidades(self) -> list[Finalidade]:
        return [c["finalidade"] for c in self.chamadas]
