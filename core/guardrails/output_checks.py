"""Guardrails de saída: aplicados a toda resposta antes do envio (FR-006, FR-009, R-10).

Ordem fixa: confiança mínima, tópico proibido, desconto acima do limite, valor não fundamentado.
A primeira regra que dispara define o motivo. Funções puras, sem I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from core.guardrails.base import APROVADO, ResultadoGuardrail, normalizar, reprovado


@dataclass(frozen=True)
class ConfigGuardrails:
    confianca_minima: float
    topicos_proibidos: Sequence[str]
    limite_desconto_percentual: float


_DINHEIRO_RS = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?")
_DINHEIRO_REAIS = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?\s*reais")
_PERCENTUAL = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_HORARIO = re.compile(r"(?<![\d.,])(\d{1,2})\s?(?:h(?:oras?)?(\d{2})?|:(\d{2}))(?![a-z])")
_SENTENCA = re.compile(r"[.!?\n]+")


def _decimal(texto: str) -> Decimal:
    return Decimal(texto.replace(".", "").replace(",", ".")) if "," in texto else Decimal(texto)


def _valores(texto: str) -> list[tuple[str, str]]:
    """Valores citados (dinheiro, percentual, horário) como (chave canônica, texto original)."""
    norm = normalizar(texto)
    achados: list[tuple[int, str, str]] = []
    for padrao in (_DINHEIRO_RS, _DINHEIRO_REAIS):
        for m in padrao.finditer(texto if padrao is _DINHEIRO_RS else norm):
            inteiro = m.group(1).replace(".", "")
            valor = Decimal(f"{inteiro}.{m.group(2) or '0'}")
            achados.append((m.start(), f"din:{valor.normalize():f}", m.group(0).strip()))
    for m in _PERCENTUAL.finditer(norm):
        valor = _decimal(m.group(1))
        achados.append((m.start(), f"pct:{valor.normalize():f}", m.group(0).strip()))
    for m in _HORARIO.finditer(norm):
        hora, minuto = int(m.group(1)), int(m.group(2) or m.group(3) or 0)
        achados.append((m.start(), f"hor:{hora}:{minuto:02d}", m.group(0).strip()))
    achados.sort()
    return [(chave, original) for _, chave, original in achados]


def _desconto_acima_do_limite(resposta: str, limite: float) -> bool:
    for sentenca in _SENTENCA.split(normalizar(resposta)):
        if "desconto" not in sentenca:
            continue
        for m in _PERCENTUAL.finditer(sentenca):
            if _decimal(m.group(1)) > Decimal(str(limite)):
                return True
    return False


def _chaves(textos: Iterable[str]) -> set[str]:
    return {chave for texto in textos for chave, _ in _valores(texto)}


def checar_saida(
    resposta: str, trechos: Sequence[str], confianca: float, config: ConfigGuardrails
) -> ResultadoGuardrail:
    """Reprova resposta com confiança baixa, tópico proibido, desconto acima do limite ou valor inventado.

    Motivos: `confianca_abaixo_do_minimo`, `topico_proibido:<termo>`, `desconto_acima_do_limite`,
    `valor_nao_fundamentado:<valor>`.
    """
    if confianca < config.confianca_minima:
        return reprovado("confianca_abaixo_do_minimo")

    texto = normalizar(resposta)
    for termo in config.topicos_proibidos:
        if normalizar(termo) in texto:
            return reprovado(f"topico_proibido:{termo}")

    if _desconto_acima_do_limite(resposta, config.limite_desconto_percentual):
        return reprovado("desconto_acima_do_limite")

    fundamentados = _chaves(trechos)
    for chave, original in _valores(resposta):
        if chave not in fundamentados:
            return reprovado(f"valor_nao_fundamentado:{original}")

    return APROVADO
