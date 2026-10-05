"""Composição das dependências concretas (cliente LLM, canal). Usada pela API e pelo worker."""

from __future__ import annotations

from core.llm.openrouter import OpenRouterClient
from core.llm.ports import LLMClient
from core.ports.channel import MessageChannel
from integrations.whatsapp.client import WhatsAppClient


def build_llm_client() -> LLMClient:
    return OpenRouterClient()


def build_channel() -> MessageChannel:
    return WhatsAppClient()
