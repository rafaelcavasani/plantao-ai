"""Tabela estática de preços, usada quando o gateway não devolve o custo da chamada."""

from __future__ import annotations

from decimal import Decimal

# (US$ por 1 M de tokens de entrada, US$ por 1 M de tokens de saída)
_PRECOS: dict[str, tuple[Decimal, Decimal]] = {
    "anthropic/claude-3-haiku": (Decimal("0.25"), Decimal("1.25")),
    "anthropic/claude-3.5-sonnet": (Decimal("3.00"), Decimal("15.00")),
    "openai/text-embedding-3-small": (Decimal("0.02"), Decimal("0")),
}
_PADRAO = (Decimal("0.50"), Decimal("1.50"))  # estimativa conservadora para modelo desconhecido
_MILHAO = Decimal(1_000_000)


def estimar_custo(modelo: str, tokens_entrada: int, tokens_saida: int) -> Decimal:
    preco_in, preco_out = _PRECOS.get(modelo, _PADRAO)
    return (preco_in * tokens_entrada + preco_out * tokens_saida) / _MILHAO
