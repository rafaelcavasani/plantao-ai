"""Mascaramento de dados pessoais para logs (FR-022)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Sequência de 10 a 15 dígitos, com separadores comuns de telefone, opcionalmente com "+" na frente.
_TELEFONE = re.compile(r"\+?\d(?:[\s().-]{0,2}\d){9,14}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CHAVES_SENSIVEIS = frozenset(
    {
        "nome",
        "telefone",
        "contato",
        "phone",
        "number",
        "remotejid",
        "email",
        "pushname",
        "contato_enc",
    }
)


def mascarar_telefone(texto: str) -> str:
    """Troca todos os dígitos de cada telefone por `*`, exceto os 4 últimos."""

    def _mascara(match: re.Match[str]) -> str:
        bruto = match.group(0)
        digitos = [c for c in bruto if c.isdigit()]
        visiveis = "".join(digitos[-4:])
        return "*" * (len(digitos) - 4) + visiveis

    return _TELEFONE.sub(_mascara, texto)


def mascarar_texto(texto: str) -> str:
    """Mascara telefones e e-mails em texto livre."""
    return _EMAIL.sub("***@***", mascarar_telefone(texto))


def mascarar_dados(valor: Any) -> Any:
    """Mascara recursivamente dicts e listas: chaves sensíveis viram `***`; strings passam pelo filtro."""
    if isinstance(valor, Mapping):
        return {
            chave: "***" if str(chave).lower() in _CHAVES_SENSIVEIS else mascarar_dados(item)
            for chave, item in valor.items()
        }
    if isinstance(valor, list | tuple):
        return [mascarar_dados(item) for item in valor]
    if isinstance(valor, str):
        return mascarar_texto(valor)
    return valor
