"""Leituras do painel de operação (spec 004). Tudo passa por `painel_session()` (papel `plantao_painel`).

Esse papel só enxerga tabelas agregadas e metadados (ADR-0006/0008): nenhuma consulta daqui lê texto de
mensagem, contato ou credencial, e consultas com `SELECT *` em tabelas de conteúdo falham no banco.
Todo SQL liga parâmetros (nunca concatena texto vindo do operador); ordenação só por colunas de whitelist.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.painel import planos
from core.painel.atencao import EntradaAtencao, avaliar, limites_atuais
from db.painel import painel_session

__all__ = [
    "COLUNAS_DE_ORDEM",
    "serie_do_periodo",
    "DESATUALIZADO_APOS_S",
    "FUSO",
    "FiltrosLista",
    "exportar_csv",
    "janela",
    "listar_empresas",
    "saude_dos_dados",
    "visao_geral",
]

FUSO: Final = "America/Sao_Paulo"
_TZ = ZoneInfo(FUSO)
DESATUALIZADO_APOS_S: Final = 600  # 10 minutos sem atualização (FR-027)
DIAS_DO_PERIODO: Final = {"hoje": 1, "7d": 7, "30d": 30}
DIAS_DO_MES: Final = 30
ESTADOS: Final = ("ativo", "em_configuracao", "suspenso", "encerrado")


def _f(valor: Any) -> float:
    return float(valor) if valor is not None else 0.0


def _i(valor: Any) -> int:
    return int(valor) if valor is not None else 0


def _iso(momento: datetime | None) -> str | None:
    return momento.astimezone(UTC).isoformat() if momento else None


# --- Janelas de tempo ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Janela:
    """Período corrente `[inicio, fim)` e o de mesma duração imediatamente anterior, em UTC."""

    periodo: str
    dias: int
    inicio: datetime
    fim: datetime
    anterior_inicio: datetime
    inicio_30d: datetime


def janela(periodo: str, agora: datetime | None = None) -> Janela:
    """`hoje` = desde 00:00 de São Paulo; `7d`/`30d` = os últimos 7 ou 30 dias de calendário, incluindo hoje."""
    agora = (agora or datetime.now(UTC)).astimezone(UTC)
    dias = DIAS_DO_PERIODO[periodo]
    meia_noite = agora.astimezone(_TZ).replace(hour=0, minute=0, second=0, microsecond=0)

    def dia(offset: int) -> datetime:
        return (meia_noite - timedelta(days=offset)).astimezone(UTC)

    inicio = dia(dias - 1)
    return Janela(
        periodo=periodo,
        dias=dias,
        inicio=inicio,
        fim=agora,
        anterior_inicio=dia(2 * dias - 1),
        inicio_30d=dia(DIAS_DO_MES - 1),
    )


# --- Dados por empresa --------------------------------------------------------------------------

_SQL_EMPRESAS = text(
    """
    SELECT t.id, t.slug, t.nome_empresa, t.nicho, t.plano, t.status, t.criado_em, t.ativado_em,
           t.encerrado_em, t.dados_apagados_em, t.versao,
           s.ultima_mensagem_em, s.ultimo_remetente, s.conversas_abertas, s.conversas_handoff,
           s.documentos, s.trechos, s.atualizado_em AS situacao_em,
           c.instance_name, c.verificada_em
    FROM tenants t
    LEFT JOIN painel_situacao s ON s.tenant_id = t.id
    LEFT JOIN channel_connections c ON c.tenant_id = t.id AND c.canal = 'whatsapp'
    ORDER BY t.slug
    """
)

_SQL_SOMAS = text(
    """
    SELECT tenant_id,
      coalesce(sum(msgs_lead) FILTER (WHERE hora >= :ini AND hora < :fim), 0) AS lead,
      coalesce(sum(msgs_agente) FILTER (WHERE hora >= :ini AND hora < :fim), 0) AS agente,
      coalesce(sum(msgs_humano) FILTER (WHERE hora >= :ini AND hora < :fim), 0) AS humano,
      coalesce(sum(conversas_iniciadas) FILTER (WHERE hora >= :ini AND hora < :fim), 0) AS conversas,
      coalesce(sum(handoffs) FILTER (WHERE hora >= :ini AND hora < :fim), 0) AS handoffs,
      coalesce(sum(handoffs_resolvidos) FILTER (WHERE hora >= :ini AND hora < :fim), 0) AS resolvidos,
      coalesce(sum(falhas_envio) FILTER (WHERE hora >= :ini AND hora < :fim), 0) AS falhas,
      coalesce(sum(custo_usd) FILTER (WHERE hora >= :ini AND hora < :fim), 0) AS custo,
      coalesce(sum(tokens_entrada + tokens_saida) FILTER (WHERE hora >= :ini AND hora < :fim), 0) AS tokens,
      coalesce(sum(msgs_lead) FILTER (WHERE hora >= :ant AND hora < :ini), 0) AS a_lead,
      coalesce(sum(msgs_agente) FILTER (WHERE hora >= :ant AND hora < :ini), 0) AS a_agente,
      coalesce(sum(msgs_humano) FILTER (WHERE hora >= :ant AND hora < :ini), 0) AS a_humano,
      coalesce(sum(conversas_iniciadas) FILTER (WHERE hora >= :ant AND hora < :ini), 0) AS a_conversas,
      coalesce(sum(handoffs) FILTER (WHERE hora >= :ant AND hora < :ini), 0) AS a_handoffs,
      coalesce(sum(custo_usd) FILTER (WHERE hora >= :ant AND hora < :ini), 0) AS a_custo,
      coalesce(sum(custo_usd) FILTER (WHERE hora >= :ini30 AND hora < :fim), 0) AS custo_30d
    FROM painel_agregado_hora
    WHERE hora >= least(:ant, :ini30) AND hora < :fim
    GROUP BY tenant_id
    """
)

_VAZIO: Final = {
    k: 0
    for k in (
        "lead agente humano conversas handoffs resolvidos falhas custo tokens a_lead a_agente a_humano "
        "a_conversas a_handoffs a_custo custo_30d"
    ).split()
}


async def _empresas(s: AsyncSession) -> list[dict[str, Any]]:
    return [dict(r) for r in (await s.execute(_SQL_EMPRESAS)).mappings().all()]


async def _somas(s: AsyncSession, j: Janela) -> dict[Any, dict[str, Any]]:
    linhas = await s.execute(
        _SQL_SOMAS, {"ini": j.inicio, "fim": j.fim, "ant": j.anterior_inicio, "ini30": j.inicio_30d}
    )
    return {r["tenant_id"]: dict(r) for r in linhas.mappings().all()}


def _conexao(emp: dict[str, Any]) -> str:
    if emp["instance_name"] is None:
        return "sem_conexao"
    return "verificada" if emp["verificada_em"] is not None else "nao_verificada"


def _minutos(agora: datetime, momento: datetime | None) -> float | None:
    return (agora - momento).total_seconds() / 60 if momento else None


def _item(emp: dict[str, Any], soma: dict[str, Any], j: Janela, agora: datetime) -> dict[str, Any]:
    custo_30d = _f(soma["custo_30d"])
    pct = planos.orcamento_pct(custo_30d, emp["plano"])
    atencao = avaliar(
        EntradaAtencao(
            estado=emp["status"],
            minutos_desde_ultima=_minutos(agora, emp["ultima_mensagem_em"]),
            minutos_desde_ativacao=_minutos(agora, emp["ativado_em"]),
            conversas=_i(soma["conversas"]),
            handoffs=_i(soma["handoffs"]),
            falhas_envio=_i(soma["falhas"]),
            conexao=_conexao(emp),
            orcamento_pct=pct,
        ),
        limites_atuais(),
    )
    return {
        "slug": emp["slug"],
        "nome": emp["nome_empresa"],
        "nicho": emp["nicho"],
        "plano": planos.chave_do_plano(emp["plano"]),
        "estado": emp["status"],
        "criada_em": _iso(emp["criado_em"]),
        "ativada_em": _iso(emp["ativado_em"]),
        "mensagens": _i(soma["lead"]) + _i(soma["agente"]) + _i(soma["humano"]),
        "conversas_abertas": _i(emp["conversas_abertas"]),
        "handoffs": _i(soma["handoffs"]),
        "ultima_mensagem": (
            {"em": _iso(emp["ultima_mensagem_em"]), "remetente": emp["ultimo_remetente"]}
            if emp["ultima_mensagem_em"]
            else None
        ),
        "custo_usd": round(_f(soma["custo"]), 4),
        "orcamento_usd": planos.orcamento_do_plano(emp["plano"]),
        "orcamento_pct": None if pct is None else round(pct, 1),
        "conexao": _conexao(emp),
        "documentos": _i(emp["documentos"]),
        "atencao": [
            {"codigo": a.codigo, "gravidade": a.gravidade, "detalhe": a.detalhe} for a in atencao
        ],
    }


def _atualizado_em(empresas: list[dict[str, Any]]) -> str | None:
    marcas = [e["situacao_em"] for e in empresas if e["situacao_em"] is not None]
    return _iso(min(marcas)) if marcas else None


# --- Visão geral --------------------------------------------------------------------------------


def _soma(linhas: list[dict[str, Any]], campo: str) -> float:
    return sum(_f(x[campo]) for x in linhas)


def _variacao(atual: float, anterior: float) -> dict[str, float]:
    return {"valor": atual, "anterior": anterior}


async def serie_do_periodo(
    s: AsyncSession, j: Janela, tenant_id: Any = None
) -> list[dict[str, Any]]:
    """Pontos com todos os baldes do período (zeros incluídos): 3 h em `hoje`, dia em `7d`, 3 dias em `30d`."""
    linhas = (
        (
            await s.execute(
                text(
                    "SELECT hora, sum(msgs_lead) AS recebidas, sum(msgs_agente) AS agente, "
                    "sum(msgs_humano) AS humano, sum(handoffs) AS handoffs, "
                    "sum(conversas_iniciadas) AS conversas, "
                    "sum(tokens_entrada + tokens_saida) AS tokens, sum(custo_usd) AS custo "
                    "FROM painel_agregado_hora "
                    "WHERE hora >= :ini AND hora < :fim AND (CAST(:t AS uuid) IS NULL OR tenant_id = :t) "
                    "GROUP BY hora"
                ),
                {"ini": j.inicio, "fim": j.fim, "t": tenant_id},
            )
        )
        .mappings()
        .all()
    )
    local_ini = j.inicio.astimezone(_TZ)

    def chave(momento: datetime) -> int:
        local = momento.astimezone(_TZ)
        if j.periodo == "hoje":
            return local.hour // 3
        dia = (local.date() - local_ini.date()).days
        return dia if j.periodo == "7d" else dia // 3

    def inicio_do_balde(n: int) -> datetime:
        if j.periodo == "hoje":
            return (local_ini + timedelta(hours=3 * n)).astimezone(UTC)
        passo = 1 if j.periodo == "7d" else 3
        return (local_ini + timedelta(days=passo * n)).astimezone(UTC)

    total = {"hoje": 8, "7d": 7, "30d": 10}[j.periodo]
    pontos: list[dict[str, Any]] = [
        {
            "inicio": _iso(inicio_do_balde(n)),
            "recebidas": 0,
            "agente": 0,
            "humano": 0,
            "handoffs": 0,
            "conversas": 0,
            "tokens": 0,
            "custo_usd": 0.0,
        }
        for n in range(total)
    ]
    for r in linhas:
        n = chave(r["hora"])
        if 0 <= n < total:
            pontos[n]["recebidas"] += _i(r["recebidas"])
            pontos[n]["agente"] += _i(r["agente"])
            pontos[n]["humano"] += _i(r["humano"])
            pontos[n]["handoffs"] += _i(r["handoffs"])
            pontos[n]["conversas"] += _i(r["conversas"])
            pontos[n]["tokens"] += _i(r["tokens"])
            pontos[n]["custo_usd"] = round(pontos[n]["custo_usd"] + _f(r["custo"]), 4)
    if j.periodo == "hoje":  # só até o balde corrente
        corrente = j.fim.astimezone(_TZ).hour // 3
        pontos = pontos[: corrente + 1]
    return pontos


async def visao_geral(periodo: str, agora: datetime | None = None) -> dict[str, Any]:
    agora = (agora or datetime.now(UTC)).astimezone(UTC)
    j = janela(periodo, agora)
    async with painel_session() as s:
        empresas = await _empresas(s)
        somas = await _somas(s, j)
        serie = await serie_do_periodo(s, j)
    itens = [_item(e, somas.get(e["id"], _VAZIO), j, agora) for e in empresas]
    linhas = [somas.get(e["id"], _VAZIO) for e in empresas]

    por_estado = {estado: 0 for estado in ESTADOS}
    for e in empresas:
        por_estado[e["status"]] = por_estado.get(e["status"], 0) + 1

    conversas, handoffs = _soma(linhas, "conversas"), _soma(linhas, "handoffs")
    a_conv, a_hand = _soma(linhas, "a_conversas"), _soma(linhas, "a_handoffs")
    mensagens = _soma(linhas, "lead") + _soma(linhas, "agente") + _soma(linhas, "humano")
    a_mensagens = _soma(linhas, "a_lead") + _soma(linhas, "a_agente") + _soma(linhas, "a_humano")

    margem, disponivel = 0.0, True
    for e, linha in zip(empresas, linhas, strict=True):
        if e["status"] == "encerrado":
            continue
        m = planos.margem_estimada(e["plano"], _f(linha["custo"]), j.dias)
        if m is None:
            disponivel = False
        else:
            margem += m

    funil = {
        "conversas": int(conversas),
        "respondidas_agente": int(max(conversas - handoffs, 0)),
        "handoff": int(handoffs),
        "resolvidas_humano": int(_soma(linhas, "resolvidos")),
    }
    return {
        "periodo": periodo,
        "fuso": FUSO,
        "atualizado_em": _atualizado_em(empresas),
        "empresas_por_estado": {**por_estado, "total": len(empresas)},
        "totais": {
            "mensagens": {
                **_variacao(mensagens, a_mensagens),
                "recebidas": int(_soma(linhas, "lead")),
                "agente": int(_soma(linhas, "agente")),
                "humano": int(_soma(linhas, "humano")),
            },
            "conversas": {
                **_variacao(conversas, a_conv),
                "abertas": sum(_i(e["conversas_abertas"]) for e in empresas),
                "handoff": sum(_i(e["conversas_handoff"]) for e in empresas),
            },
            "taxa_handoff_pct": _variacao(
                round(handoffs / conversas * 100, 1) if conversas else 0.0,
                round(a_hand / a_conv * 100, 1) if a_conv else 0.0,
            ),
            "custo_usd": _variacao(
                round(_soma(linhas, "custo"), 4), round(_soma(linhas, "a_custo"), 4)
            ),
            "margem_usd": {
                "valor": round(margem, 2) if disponivel else None,
                "disponivel": disponivel,
            },
        },
        "serie": serie,
        "funil": funil,
        "atencao": sorted(
            (
                {
                    "slug": i["slug"],
                    "nome": i["nome"],
                    "motivos": [a["codigo"] for a in i["atencao"]],
                    "gravidade": i["atencao"][0]["gravidade"],
                    "detalhe": "; ".join(a["detalhe"] for a in i["atencao"]),
                }
                for i in itens
                if i["atencao"]
            ),
            key=lambda a: (0 if a["gravidade"] == "critica" else 1, a["nome"]),
        ),
    }


# --- Lista de empresas --------------------------------------------------------------------------

COLUNAS_DE_ORDEM: Final[dict[str, Callable[[dict[str, Any]], Any]]] = {
    "nome": lambda i: i["nome"].lower(),
    "estado": lambda i: ESTADOS.index(i["estado"]) if i["estado"] in ESTADOS else 99,
    "mensagens": lambda i: i["mensagens"],
    "abertas": lambda i: i["conversas_abertas"],
    "handoffs": lambda i: i["handoffs"],
    "ultima_mensagem": lambda i: i["ultima_mensagem"]["em"] if i["ultima_mensagem"] else "",
    "custo": lambda i: i["custo_usd"],
    "orcamento": lambda i: -1.0 if i["orcamento_pct"] is None else i["orcamento_pct"],
    "criada_em": lambda i: i["criada_em"] or "",
}


@dataclass(frozen=True)
class FiltrosLista:
    periodo: str = "30d"
    q: str | None = None
    estado: str | None = None
    nicho: str | None = None
    ordem: str = "nome"
    sentido: str = "asc"
    pagina: int = 1
    tamanho: int = 25


async def _itens_filtrados(
    f: FiltrosLista, agora: datetime
) -> tuple[list[dict[str, Any]], str | None]:
    j = janela(f.periodo, agora)
    async with painel_session() as s:
        empresas = await _empresas(s)
        somas = await _somas(s, j)
    itens = [_item(e, somas.get(e["id"], _VAZIO), j, agora) for e in empresas]
    termo = (f.q or "").strip().lower()
    itens = [
        i
        for i in itens
        if (not termo or termo in i["nome"].lower() or termo in i["slug"])
        and (not f.estado or i["estado"] == f.estado)
        and (not f.nicho or i["nicho"] == f.nicho)
    ]
    chave = COLUNAS_DE_ORDEM[f.ordem]
    vazios = [i for i in itens if f.ordem == "ultima_mensagem" and not i["ultima_mensagem"]]
    com_valor = [i for i in itens if i not in vazios]
    com_valor.sort(key=chave, reverse=f.sentido == "desc")
    return com_valor + vazios, _atualizado_em(empresas)


async def listar_empresas(f: FiltrosLista, agora: datetime | None = None) -> dict[str, Any]:
    agora = (agora or datetime.now(UTC)).astimezone(UTC)
    itens, atualizado = await _itens_filtrados(f, agora)
    inicio = (f.pagina - 1) * f.tamanho
    return {
        "total": len(itens),
        "pagina": f.pagina,
        "tamanho": f.tamanho,
        "atualizado_em": atualizado,
        "itens": itens[inicio : inicio + f.tamanho],
    }


CABECALHO_CSV: Final = (
    "slug",
    "nome",
    "nicho",
    "plano",
    "estado",
    "criada_em",
    "mensagens",
    "conversas_abertas",
    "handoffs",
    "minutos_desde_ultima_mensagem",
    "custo_usd",
)


def _neutraliza_formula(valor: str) -> str:
    """Planilhas executam texto que começa com = + - @; prefixa aspa simples para virar texto."""
    return "'" + valor if valor[:1] in ("=", "+", "-", "@", "\t", "\r") else valor


async def exportar_csv(f: FiltrosLista, agora: datetime | None = None) -> str:
    """CSV (separador `;`, com BOM) dos itens filtrados, sem paginação e sem dado pessoal (FR-015)."""
    agora = (agora or datetime.now(UTC)).astimezone(UTC)
    itens, _ = await _itens_filtrados(f, agora)
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\n")
    escritor.writerow(CABECALHO_CSV)
    for i in itens:
        ultima = i["ultima_mensagem"]
        minutos: int | str = ""
        if ultima:
            minutos = int((agora - datetime.fromisoformat(ultima["em"])).total_seconds() // 60)
        escritor.writerow(
            [
                _neutraliza_formula(str(i["slug"])),
                _neutraliza_formula(str(i["nome"])),
                _neutraliza_formula(str(i["nicho"])),
                i["plano"],
                i["estado"],
                i["criada_em"],
                i["mensagens"],
                i["conversas_abertas"],
                i["handoffs"],
                minutos,
                i["custo_usd"],
            ]
        )
    return "﻿" + saida.getvalue()


# --- Saúde dos números --------------------------------------------------------------------------


async def saude_dos_dados(agora: datetime | None = None) -> dict[str, Any]:
    """Quando o job de agregação gravou pela última vez e se os dados estão velhos demais."""
    async with painel_session() as s:
        ultimo = (
            await s.execute(text("SELECT max(atualizado_em) FROM painel_situacao"))
        ).scalar_one()
    if ultimo is None:
        return {"atualizado_em": None, "idade_s": None, "desatualizado": False}
    idade = ((agora or datetime.now(UTC)) - ultimo).total_seconds()
    return {
        "atualizado_em": _iso(ultimo),
        "idade_s": round(max(idade, 0.0)),
        "desatualizado": idade > DESATUALIZADO_APOS_S,
    }
