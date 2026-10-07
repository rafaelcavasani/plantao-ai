"""Regras de atenção do painel (spec 004, FR-011 e FR-012). Funções puras, sem I/O.

Uma empresa "pede atenção" por um ou mais motivos. Os limites vêm de `PAINEL_LIMITE_*` (padrão: 24 h sem mensagem,
30% de handoff, 90% do orçamento mensal). O alerta de handoff só vale com amostra mínima de conversas, para uma
empresa com 1 conversa e 1 handoff não aparecer como "100%".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from core.config import settings

__all__ = [
    "AMOSTRA_MINIMA_CONVERSAS",
    "Atencao",
    "EntradaAtencao",
    "Limites",
    "avaliar",
    "limites_atuais",
]

AMOSTRA_MINIMA_CONVERSAS: Final = 5

Gravidade = Literal["critica", "aviso"]
CodigoAtencao = Literal[
    "sem_atividade", "handoff_alto", "custo_alto", "conexao_nao_verificada", "falhas_envio"
]
ORDEM_DE_GRAVIDADE: Final = {"critica": 0, "aviso": 1}


@dataclass(frozen=True)
class Limites:
    silencio_horas: float
    handoff_pct: float
    custo_pct: float


def limites_atuais() -> Limites:
    return Limites(
        silencio_horas=settings.painel_limite_silencio_horas,
        handoff_pct=settings.painel_limite_handoff_pct,
        custo_pct=settings.painel_limite_custo_pct,
    )


@dataclass(frozen=True)
class EntradaAtencao:
    estado: str
    # Minutos desde a última mensagem; `None` se nunca houve. `minutos_desde_ativacao` serve de referência então.
    minutos_desde_ultima: float | None
    minutos_desde_ativacao: float | None
    conversas: int
    handoffs: int
    falhas_envio: int
    conexao: str  # verificada | nao_verificada | sem_conexao
    orcamento_pct: (
        float | None
    )  # custo dos últimos 30 dias sobre o orçamento do plano; None sem orçamento


@dataclass(frozen=True)
class Atencao:
    codigo: CodigoAtencao
    gravidade: Gravidade
    detalhe: str


def _pt(valor: float, casas: int = 1) -> str:
    return f"{valor:.{casas}f}".replace(".", ",")


def _duracao(minutos: float) -> str:
    return f"{int(minutos // 60)} h" if minutos >= 120 else f"{int(minutos)} min"


def avaliar(entrada: EntradaAtencao, limites: Limites) -> list[Atencao]:
    """Motivos de atenção da empresa, do mais grave ao menos grave. Empresa encerrada nunca alerta."""
    if entrada.estado == "encerrado":
        return []
    achados: list[Atencao] = []
    ativa = entrada.estado == "ativo"

    if ativa and entrada.conexao != "verificada":
        texto = (
            "conexão do canal não verificada"
            if entrada.conexao == "nao_verificada"
            else "sem conexão do canal"
        )
        achados.append(Atencao("conexao_nao_verificada", "critica", texto))

    if entrada.orcamento_pct is not None and entrada.orcamento_pct >= limites.custo_pct:
        achados.append(
            Atencao(
                "custo_alto",
                "critica" if entrada.orcamento_pct >= 100 else "aviso",
                f"custo em {_pt(entrada.orcamento_pct, 0)}% do orçamento mensal",
            )
        )

    if ativa:
        referencia = (
            entrada.minutos_desde_ultima
            if entrada.minutos_desde_ultima is not None
            else entrada.minutos_desde_ativacao
        )
        if referencia is not None and referencia > limites.silencio_horas * 60:
            quando = (
                "sem mensagens há "
                if entrada.minutos_desde_ultima is not None
                else "sem mensagens desde a ativação, há "
            )
            achados.append(Atencao("sem_atividade", "aviso", quando + _duracao(referencia)))

    if entrada.conversas >= AMOSTRA_MINIMA_CONVERSAS:
        taxa = entrada.handoffs / entrada.conversas * 100
        if taxa > limites.handoff_pct:
            achados.append(
                Atencao(
                    "handoff_alto",
                    "aviso",
                    f"taxa de handoff {_pt(taxa)}% (limite {_pt(limites.handoff_pct, 0)}%)",
                )
            )

    if entrada.falhas_envio > 0:
        achados.append(
            Atencao("falhas_envio", "aviso", f"{entrada.falhas_envio} falha(s) de envio no período")
        )

    return sorted(achados, key=lambda a: ORDEM_DE_GRAVIDADE[a.gravidade])
