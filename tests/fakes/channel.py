"""`FakeChannel` e `FakeQueue` para testes."""

from __future__ import annotations

from typing import Any

from core.ports.channel import ChannelError, ConexaoCanal, EstadoConexao


class FakeChannel:
    """Canal falso. Registra cada envio com a instância da conexão usada.

    `enviadas` guarda `(contato, texto)` e `envios` guarda `(instance_name, contato, texto)`.
    `falhar` faz todo envio falhar; `falhar_instancias` só os das instâncias indicadas.
    `estados` define o resultado de `verificar` por instância (padrão: `estado_padrao`).
    """

    def __init__(
        self,
        *,
        falhar: bool = False,
        falhar_instancias: set[str] | None = None,
        estados: dict[str, EstadoConexao] | None = None,
        estado_padrao: EstadoConexao = EstadoConexao.CONECTADA,
    ) -> None:
        self.falhar = falhar
        self.falhar_instancias = falhar_instancias or set()
        self.estados = estados or {}
        self.estado_padrao = estado_padrao
        self.enviadas: list[tuple[str, str]] = []
        self.envios: list[tuple[str, str, str]] = []
        self.verificadas: list[str] = []

    async def send_text(self, conexao: ConexaoCanal, contato: str, texto: str) -> None:
        if self.falhar or conexao.instance_name in self.falhar_instancias:
            raise ChannelError("falha simulada")
        self.enviadas.append((contato, texto))
        self.envios.append((conexao.instance_name, contato, texto))

    async def verificar(self, conexao: ConexaoCanal) -> EstadoConexao:
        self.verificadas.append(conexao.instance_name)
        return self.estados.get(conexao.instance_name, self.estado_padrao)


class FakeQueue:
    """Substitui o pool do ARQ: guarda os jobs enfileirados."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, funcao: str, *args: Any, **kwargs: Any) -> None:
        self.jobs.append((funcao, args, kwargs))
