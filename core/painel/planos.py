"""Orçamento e preço dos planos para o painel (spec 004, FR-043 e FR-044).

Funções puras sobre `db.config_planos`. Valor ausente nunca vira zero: o chamador recebe `None` e mostra
"sem orçamento" ou "margem indisponível".
"""

from __future__ import annotations

from db.config_planos import PLANO_PADRAO, PLANOS

__all__ = [
    "chave_do_plano",
    "listar_planos",
    "margem_estimada",
    "nome_do_plano",
    "orcamento_do_plano",
    "orcamento_pct",
    "preco_do_plano",
]

DIAS_DO_MES = 30


def chave_do_plano(plano: str | None) -> str:
    """Chave conhecida do plano; plano desconhecido ou vazio cai no padrão."""
    return plano if plano in PLANOS else PLANO_PADRAO


def nome_do_plano(plano: str | None) -> str:
    return PLANOS[chave_do_plano(plano)]["nome"]


def orcamento_do_plano(plano: str | None) -> float | None:
    return PLANOS[chave_do_plano(plano)]["orcamento_mensal_usd"]


def preco_do_plano(plano: str | None) -> float | None:
    return PLANOS[chave_do_plano(plano)]["preco_mensal_usd"]


def orcamento_pct(custo_mensal_usd: float, plano: str | None) -> float | None:
    """Custo do mês em % do orçamento do plano; `None` sem orçamento (ou orçamento zero)."""
    orcamento = orcamento_do_plano(plano)
    if not orcamento:
        return None
    return custo_mensal_usd / orcamento * 100


def margem_estimada(plano: str | None, custo_usd: float, dias_do_periodo: int) -> float | None:
    """Preço do plano proporcional ao período menos o custo de API; `None` sem preço."""
    preco = preco_do_plano(plano)
    if preco is None:
        return None
    return preco * dias_do_periodo / DIAS_DO_MES - custo_usd


def listar_planos() -> list[dict[str, object]]:
    return [
        {
            "chave": chave,
            "nome": plano["nome"],
            "orcamento_mensal_usd": plano["orcamento_mensal_usd"],
            "preco_mensal_usd": plano["preco_mensal_usd"],
        }
        for chave, plano in PLANOS.items()
    ]
