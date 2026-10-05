"""Utilitários de prompt e de parse de saída estruturada (R-10, R-11)."""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from core.llm.ports import SaidaInvalida

M = TypeVar("M", bound=BaseModel)

_CERCA = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def escapar(conteudo: str) -> str:
    """Impede que conteúdo não confiável feche ou abra tags de delimitação."""
    return conteudo.replace("<", "&lt;").replace(">", "&gt;")


def delimitar(tag: str, conteudo: str, **atributos: str) -> str:
    """Envolve conteúdo não confiável em `<tag ...>...</tag>` com escape. Conteúdo é dado, nunca instrução."""
    attrs = "".join(f' {nome}="{escapar(valor)}"' for nome, valor in atributos.items())
    return f"<{tag}{attrs}>{escapar(conteudo)}</{tag}>"


def parse_saida(texto: str, modelo: type[M]) -> M:
    """Converte o texto devolvido pelo LLM em `modelo`. Aceita JSON puro ou dentro de cerca ```json."""
    bruto = texto.strip()
    cerca = _CERCA.match(bruto)
    if cerca:
        bruto = cerca.group(1)
    try:
        return modelo.model_validate(json.loads(bruto))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise SaidaInvalida(type(exc).__name__) from exc
