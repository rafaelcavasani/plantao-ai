"""Cliente do WhatsApp (Evolution API no MVP; Meta Cloud API depois, ver ADR e seção 8.2).

Implementa a porta `core.ports.channel.MessageChannel`. Nenhum agente depende deste módulo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

from core.config import settings
from core.ports.channel import ChannelError

_EVENTO_MENSAGEM = "messages.upsert"


@dataclass(frozen=True)
class MensagemEntrada:
    contato: str
    external_id: str
    tipo: Literal["texto", "nao_texto"]
    conteudo: str


def parse_inbound(payload: dict[str, Any]) -> MensagemEntrada | None:
    """Converte o webhook da Evolution API em `MensagemEntrada`; `None` se for para ignorar.

    Ignora: eventos que não são mensagem, mensagens enviadas por nós (`fromMe`), grupos, status e
    payloads sem `key.id` ou `remoteJid`.
    """
    evento = str(payload.get("event", _EVENTO_MENSAGEM)).lower().replace("_", ".")
    if evento != _EVENTO_MENSAGEM:
        return None
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return None
    chave = data.get("key")
    if not isinstance(chave, dict) or chave.get("fromMe"):
        return None
    contato, external_id = chave.get("remoteJid"), chave.get("id")
    if not contato or not external_id:
        return None
    contato = str(contato)
    if contato.endswith("@g.us") or contato == "status@broadcast":
        return None
    mensagem = data.get("message")
    mensagem = mensagem if isinstance(mensagem, dict) else {}
    estendida = mensagem.get("extendedTextMessage")
    texto = mensagem.get("conversation") or (
        estendida.get("text") if isinstance(estendida, dict) else None
    )
    if isinstance(texto, str) and texto:
        return MensagemEntrada(contato, str(external_id), "texto", texto)
    return MensagemEntrada(contato, str(external_id), "nao_texto", "")


class WhatsAppClient:
    """Envio de mensagens pela Evolution API."""

    def __init__(
        self, *, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 10.0
    ) -> None:
        self._base_url = settings.whatsapp_base_url.rstrip("/")
        self._instance = settings.whatsapp_instance
        self._headers = {"apikey": settings.whatsapp_api_key}
        self._provider = settings.whatsapp_provider
        self._http = httpx.AsyncClient(transport=transport, timeout=timeout)

    async def send_text(self, contato: str, texto: str) -> None:
        if self._provider != "evolution":
            raise ChannelError(f"provedor_nao_implementado:{self._provider}")
        url = f"{self._base_url}/message/sendText/{self._instance}"
        try:
            resposta = await self._http.post(
                url, json={"number": contato, "text": texto}, headers=self._headers
            )
        except httpx.HTTPError as exc:
            raise ChannelError(type(exc).__name__) from exc
        if not resposta.is_success:
            raise ChannelError(f"http_{resposta.status_code}")

    async def aclose(self) -> None:
        await self._http.aclose()
