"""Planos do painel: orçamento mensal de custo e preço mensal, ambos em US$ (spec 004, FR-043 e FR-044).

Os valores são decisão de negócio e entram por pull request (o histórico do git é a trilha de alteração).
`None` significa "não definido": o painel mostra "sem orçamento" e "margem indisponível", nunca zero.
"""

from __future__ import annotations

from typing import Final, TypedDict


class Plano(TypedDict):
    nome: str
    orcamento_mensal_usd: float | None
    preco_mensal_usd: float | None


PLANO_PADRAO: Final = "recepcionista"

PLANOS: Final[dict[str, Plano]] = {
    "recepcionista": {
        "nome": "Recepcionista",
        "orcamento_mensal_usd": None,
        "preco_mensal_usd": None,
    },
    "recepcionista_agendador": {
        "nome": "Recepcionista + Agendador",
        "orcamento_mensal_usd": None,
        "preco_mensal_usd": None,
    },
    "pacote_completo": {
        "nome": "Pacote completo",
        "orcamento_mensal_usd": None,
        "preco_mensal_usd": None,
    },
}
