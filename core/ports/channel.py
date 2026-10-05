"""Porta de saída para mensagens ao cliente final, por conexão de empresa.

Nenhum código de `agents/` ou `core/` depende de um provedor concreto (Evolution API, Meta, Twilio).
A credencial viaja em `ConexaoCanal`, montada pelo chamador a partir do banco e descartada após o envio.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class ChannelError(Exception):
    """Falha de rede ou resposta não 2xx. A mensagem é um código curto e nunca traz credencial."""


@dataclass(frozen=True)
class ConexaoCanal:
    """Conexão de uma empresa com o provedor. Nunca serializar, logar nem enfileirar."""

    tenant_id: uuid.UUID
    canal: str  # whatsapp
    provedor: str  # evolution
    instance_name: str
    api_key: str = field(repr=False)  # chave de envio já descriptografada, só em memória


class EstadoConexao(StrEnum):
    CONECTADA = "conectada"
    DESCONECTADA = "desconectada"
    DESCONHECIDA = "desconhecida"


class MessageChannel(Protocol):
    async def send_text(self, conexao: ConexaoCanal, contato: str, texto: str) -> None:
        """Envia `texto` ao `contato` pela conexão da empresa. Levanta `ChannelError` em falha."""
        ...

    async def verificar(self, conexao: ConexaoCanal) -> EstadoConexao:
        """Consulta o estado da instância no provedor. Estado desconectado não levanta erro;
        `ChannelError` só em falha de rede ou resposta inesperada."""
        ...
