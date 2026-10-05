"""Logging estruturado em JSON, com contexto de correlação e máscara de PII (FR-013, princípio VII).

`configurar_observabilidade()` é chamado uma vez na API e uma vez no worker. Use `definir_contexto`
para anexar `correlation_id`, `tenant_id` e `conversation_id` a todos os logs do fluxo corrente.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

from core.config import settings
from core.security.pii import mascarar_dados, mascarar_texto

_CAMPOS_CONTEXTO = ("correlation_id", "tenant_id", "conversation_id")
_contexto: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "log_contexto", default=None
)


def definir_contexto(**campos: object) -> None:
    """Acrescenta campos (ignora `None`) ao contexto de log da tarefa corrente."""
    atual = dict(_contexto.get() or {})
    atual.update({k: str(v) for k, v in campos.items() if v is not None and k in _CAMPOS_CONTEXTO})
    _contexto.set(atual)


def limpar_contexto() -> None:
    _contexto.set(None)


class FiltroPII(logging.Filter):
    """Mascara telefones na mensagem e nos argumentos antes de qualquer formatação."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mascarar_texto(record.getMessage())
        record.args = None
        return True


class FormatadorJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        evento: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "nivel": record.levelname,
            "logger": record.name,
            "mensagem": mascarar_texto(record.getMessage()),
        }
        evento.update(_contexto.get() or {})
        extras = getattr(record, "dados", None)
        if extras:
            evento["dados"] = mascarar_dados(extras)
        if record.exc_info:
            evento["erro"] = mascarar_texto(self.formatException(record.exc_info))
        return json.dumps(evento, ensure_ascii=False, default=str)


def configurar_observabilidade() -> None:
    """Instala o formatador JSON no logger raiz e liga o LangSmith se houver chave."""
    manipulador = logging.StreamHandler(sys.stdout)
    manipulador.setFormatter(FormatadorJson())
    manipulador.addFilter(FiltroPII())
    raiz = logging.getLogger()
    raiz.handlers = [manipulador]
    raiz.setLevel(settings.log_level)
    if settings.langsmith_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
