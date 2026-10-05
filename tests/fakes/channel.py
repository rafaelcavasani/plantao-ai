"""`FakeChannel` e `FakeQueue` para testes."""

from __future__ import annotations

from typing import Any

from core.ports.channel import ChannelError


class FakeChannel:
    def __init__(self, *, falhar: bool = False) -> None:
        self.falhar = falhar
        self.enviadas: list[tuple[str, str]] = []

    async def send_text(self, contato: str, texto: str) -> None:
        if self.falhar:
            raise ChannelError("falha simulada")
        self.enviadas.append((contato, texto))


class FakeQueue:
    """Substitui o pool do ARQ: guarda os jobs enfileirados."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, funcao: str, *args: Any, **kwargs: Any) -> None:
        self.jobs.append((funcao, args, kwargs))
