"""Guardrails de entrada: determinísticos, antes de qualquer chamada de LLM (FR-008, FR-014, princípio V)."""

from __future__ import annotations

from collections.abc import Sequence

from core.guardrails.base import APROVADO, ResultadoGuardrail, normalizar, reprovado


def checar_entrada(mensagem: str, tipo: str, palavras_gatilho: Sequence[str]) -> ResultadoGuardrail:
    """Reprova mensagem não textual, vazia (ou só emoji/pontuação) e com palavra-gatilho.

    Motivos: `nao_texto`, `mensagem_vazia`, `palavra_gatilho:<termo>`.
    """
    if tipo != "texto":
        return reprovado("nao_texto")
    if not any(c.isalnum() for c in mensagem):
        return reprovado("mensagem_vazia")
    texto = normalizar(mensagem)
    for termo in palavras_gatilho:
        if normalizar(termo) in texto:
            return reprovado(f"palavra_gatilho:{termo}")
    return APROVADO
