"""Textos fixos enviados ao cliente final (sem LLM). Um único módulo para facilitar o ajuste de tom."""

from __future__ import annotations

TEXTO_HANDOFF = (
    "Vou pedir para um atendente da equipe continuar essa conversa com você. Obrigado por aguardar."
)
TEXTO_NAO_TEXTO = (
    "Ainda não consigo ler áudios e imagens. Vou pedir para um atendente continuar com você."
)

MOTIVO_NAO_TEXTO = "nao_texto"


def texto_para_motivo(motivo: str) -> str:
    """Texto ao cliente para um motivo de handoff. Só `nao_texto` tem texto próprio."""
    return TEXTO_NAO_TEXTO if motivo == MOTIVO_NAO_TEXTO else TEXTO_HANDOFF
