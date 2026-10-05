"""Gravação de `llm_calls` (FR-017, SC-007).

Usa sessão própria: o registro persiste mesmo se a transação do job fizer rollback.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from core.llm.ports import ChamadaLLM
from db.models import LLMCall
from db.session import tenant_session

logger = logging.getLogger("plantao.llm")

Registrador = Callable[[ChamadaLLM], Awaitable[None]]


async def gravar_chamada(chamada: ChamadaLLM) -> None:
    try:
        async with tenant_session(chamada.tenant_id) as session:
            session.add(
                LLMCall(
                    tenant_id=chamada.tenant_id,
                    conversation_id=chamada.conversation_id,
                    message_id=chamada.message_id,
                    finalidade=chamada.finalidade.value,
                    modelo=chamada.modelo,
                    tokens_entrada=chamada.uso.tokens_entrada,
                    tokens_saida=chamada.uso.tokens_saida,
                    custo_usd=chamada.uso.custo_usd,
                    latencia_ms=chamada.uso.latencia_ms,
                    sucesso=chamada.sucesso,
                    erro=chamada.erro,
                )
            )
    except Exception:
        # Falha de registro nunca deve derrubar o atendimento, mas precisa ficar visível.
        logger.exception("Falha ao gravar llm_calls")
