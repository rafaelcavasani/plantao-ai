"""Chamada de LLM com saída estruturada validada e uma nova tentativa (FR-009, R-10)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from typing import TypeVar

from pydantic import BaseModel

from core.llm.parsing import parse_saida
from core.llm.ports import Finalidade, LLMClient, Mensagem, SaidaInvalida

M = TypeVar("M", bound=BaseModel)


async def _uma_tentativa(
    llm: LLMClient,
    *,
    finalidade: Finalidade,
    modelo: str,
    mensagens: Sequence[Mensagem],
    schema: type[M],
    validar: Callable[[M], None] | None,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    message_id: uuid.UUID | None,
) -> M:
    resultado = await llm.complete_json(
        finalidade=finalidade,
        modelo=modelo,
        mensagens=mensagens,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message_id=message_id,
    )
    saida = parse_saida(resultado.texto, schema)
    if validar is not None:
        validar(saida)
    return saida


async def completar_estruturado(
    llm: LLMClient,
    *,
    finalidade: Finalidade,
    modelo: str,
    mensagens: Sequence[Mensagem],
    schema: type[M],
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
    validar: Callable[[M], None] | None = None,
) -> M:
    """Chama o LLM e valida a saída contra `schema`.

    Em `SaidaInvalida` (JSON inválido, schema ou `validar` reprovando) tenta mais uma vez; se a segunda
    também falhar, propaga `SaidaInvalida`. `LLMError` (rede, timeout) propaga sem nova tentativa aqui,
    pois o cliente já faz o seu retry.
    """
    kwargs = {
        "finalidade": finalidade,
        "modelo": modelo,
        "mensagens": mensagens,
        "schema": schema,
        "validar": validar,
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
    }
    try:
        return await _uma_tentativa(llm, **kwargs)  # type: ignore[arg-type]
    except SaidaInvalida:
        return await _uma_tentativa(llm, **kwargs)  # type: ignore[arg-type]
