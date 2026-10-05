"""Texto: normalização compartilhada pelos guardrails."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class ResultadoGuardrail:
    aprovado: bool
    motivo: str | None = None


APROVADO = ResultadoGuardrail(True)


def reprovado(motivo: str) -> ResultadoGuardrail:
    return ResultadoGuardrail(False, motivo)


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos, para comparar termos sem depender de grafia."""
    decomposto = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in decomposto if not unicodedata.combining(c))
