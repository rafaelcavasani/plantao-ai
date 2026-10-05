"""Porta de saída para mensagens ao cliente final.

Nenhum código de `agents/` ou `core/` depende de um provedor concreto (Evolution API, Meta, Twilio).
"""

from __future__ import annotations

from typing import Protocol


class ChannelError(Exception):
    """Falha de rede ou resposta não 2xx ao enviar uma mensagem."""


class MessageChannel(Protocol):
    async def send_text(self, contato: str, texto: str) -> None:
        """Envia `texto` ao `contato`. Levanta `ChannelError` em falha."""
        ...
