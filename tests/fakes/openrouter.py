"""Transport httpx que imita o OpenRouter, para testar `OpenRouterClient` e pipelines sem rede."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from tests.fakes.embeddings import embed_falso

# Recebe o corpo JSON do request de chat e devolve o texto do modelo, um status HTTP (int) ou uma exceção.
ResponderChat = Callable[[dict[str, Any]], str | int | Exception]


class OpenRouterFalso:
    def __init__(self, chat: ResponderChat | None = None) -> None:
        self.chat = chat
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.transport = httpx.MockTransport(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        corpo = json.loads(request.content)
        self.requests.append((request.url.path, corpo))
        if request.url.path.endswith("/embeddings"):
            textos = corpo["input"]
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": embed_falso(t)} for i, t in enumerate(textos)
                    ],
                    "usage": {"prompt_tokens": 10 * len(textos), "total_tokens": 10 * len(textos)},
                },
            )
        if self.chat is None:
            return httpx.Response(500)
        saida = self.chat(corpo)
        if isinstance(saida, Exception):
            raise saida
        if isinstance(saida, int):
            return httpx.Response(saida)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": saida}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30},
            },
        )
