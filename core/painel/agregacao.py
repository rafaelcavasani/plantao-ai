"""Agregação do painel: recalcula, empresa por empresa e sob RLS, `painel_agregado_hora` e `painel_situacao`.

ADR-0008: cada empresa é lida dentro de `tenant_session` (o RLS vale também no cálculo), e as linhas da janela
são regravadas de forma idempotente (apaga a janela da empresa e insere o recalculado, na mesma transação).
Nada aqui guarda texto de mensagem, contato nem identificador de conversa.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.handoff.textos import MOTIVO_FALHA_CANAL, MOTIVO_NAO_TEXTO
from db.models import Tenant
from db.painel import painel_session
from db.session import tenant_session

__all__ = [
    "BALDES_RESPOSTA_S",
    "JANELA_PADRAO_HORAS",
    "RETENCAO_DIAS",
    "apagar_antigas",
    "ResultadoAgregacao",
    "balde_da_resposta",
    "media_ms",
    "p95_s",
    "inicio_da_hora",
    "recalcular_empresa",
    "recalcular_todas",
    "somar_histogramas",
]

logger = logging.getLogger("plantao.painel.agregacao")

# Limites superiores (em segundos) dos 10 primeiros baldes; o 11º é "mais de 89 s".
BALDES_RESPOSTA_S: Final[tuple[int, ...]] = (1, 2, 3, 5, 8, 13, 21, 34, 55, 89)
TAMANHO_HISTOGRAMA: Final = len(BALDES_RESPOSTA_S) + 1
JANELA_PADRAO_HORAS: Final = 3

# Motivos de handoff que NÃO são bloqueio de guardrail (entrada sem texto, falha técnica ou motivo ausente).
NAO_SAO_GUARDRAIL: Final[tuple[str, ...]] = (
    MOTIVO_NAO_TEXTO,
    MOTIVO_FALHA_CANAL,
    "mensagem_vazia",
    "desconhecido",
    "entrada_reprovada",
    "saida_reprovada",
)


# --- Funções puras ------------------------------------------------------------------------------


def inicio_da_hora(momento: datetime) -> datetime:
    """Início da hora em UTC (a chave de `painel_agregado_hora.hora`)."""
    return momento.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def balde_da_resposta(segundos: float) -> int:
    """Índice 0..10 do balde do tempo de resposta (`<= 1 s`, `<= 2 s`, ..., `> 89 s`)."""
    for indice, limite in enumerate(BALDES_RESPOSTA_S):
        if segundos <= limite:
            return indice
    return len(BALDES_RESPOSTA_S)


def somar_histogramas(histogramas: Iterable[Sequence[int]]) -> list[int]:
    total = [0] * TAMANHO_HISTOGRAMA
    for hist in histogramas:
        for i, valor in enumerate(hist[:TAMANHO_HISTOGRAMA]):
            total[i] += int(valor)
    return total


def media_ms(n: int, soma_ms: int) -> float | None:
    return soma_ms / n if n else None


def p95_s(histograma: Sequence[int]) -> float | None:
    """Estimativa do percentil 95 em segundos: limite superior do balde onde o acumulado passa de 95%."""
    total = sum(histograma)
    if not total:
        return None
    alvo = total * 0.95
    acumulado = 0
    for indice, valor in enumerate(histograma):
        acumulado += valor
        if acumulado >= alvo:
            return float(BALDES_RESPOSTA_S[min(indice, len(BALDES_RESPOSTA_S) - 1)])
    return float(BALDES_RESPOSTA_S[-1])


# --- Consultas (sob tenant_session; sempre com o filtro explícito por tenant_id) -----------------

_HORA = "date_trunc('hour', {coluna} AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"

SQL_MENSAGENS = text(
    f"""
    SELECT {_HORA.format(coluna="timestamp")} AS hora,
           count(*) FILTER (WHERE remetente = 'lead') AS msgs_lead,
           count(*) FILTER (WHERE remetente = 'agente') AS msgs_agente,
           count(*) FILTER (WHERE remetente = 'humano') AS msgs_humano,
           count(*) FILTER (WHERE tipo = 'nao_texto') AS msgs_nao_texto,
           count(*) FILTER (WHERE remetente = 'agente' AND status_envio = 'falha') AS falhas_envio
    FROM messages
    WHERE tenant_id = :t AND timestamp >= :desde AND timestamp < :ate
    GROUP BY 1
    """
)
SQL_INTENCOES = text(
    f"""
    SELECT {_HORA.format(coluna="timestamp")} AS hora, intencao, count(*) AS total
    FROM messages
    WHERE tenant_id = :t AND timestamp >= :desde AND timestamp < :ate AND intencao IS NOT NULL
    GROUP BY 1, 2
    """
)
SQL_CONVERSAS = text(
    f"""
    SELECT {_HORA.format(coluna="iniciado_em")} AS hora, count(*) AS total
    FROM conversations
    WHERE tenant_id = :t AND iniciado_em >= :desde AND iniciado_em < :ate
    GROUP BY 1
    """
)
SQL_HANDOFFS = text(
    f"""
    SELECT {_HORA.format(coluna="criado_em")} AS hora,
           count(*) AS handoffs,
           count(*) FILTER (WHERE resolvido_por_humano) AS resolvidos,
           count(*) FILTER (WHERE motivo <> ALL(:nao_guardrail)) AS bloqueios
    FROM handoff_log
    WHERE tenant_id = :t AND criado_em >= :desde AND criado_em < :ate
    GROUP BY 1
    """
)
SQL_LLM = text(
    f"""
    SELECT {_HORA.format(coluna="criado_em")} AS hora,
           coalesce(sum(tokens_entrada), 0) AS tokens_entrada,
           coalesce(sum(tokens_saida), 0) AS tokens_saida,
           coalesce(sum(custo_usd), 0) AS custo,
           coalesce(sum(custo_usd) FILTER (WHERE finalidade = 'roteador'), 0) AS custo_roteador,
           coalesce(sum(custo_usd) FILTER (WHERE finalidade = 'suporte'), 0) AS custo_suporte,
           coalesce(sum(custo_usd) FILTER (WHERE finalidade = 'embedding'), 0) AS custo_embedding
    FROM llm_calls
    WHERE tenant_id = :t AND criado_em >= :desde AND criado_em < :ate
    GROUP BY 1
    """
)
SQL_LLM_MODELO = text(
    f"""
    SELECT {_HORA.format(coluna="criado_em")} AS hora, modelo, coalesce(sum(custo_usd), 0) AS custo
    FROM llm_calls
    WHERE tenant_id = :t AND criado_em >= :desde AND criado_em < :ate
    GROUP BY 1, 2
    """
)
SQL_RESPOSTA = text(
    f"""
    SELECT {_HORA.format(coluna="r.timestamp")} AS hora,
           CASE
             WHEN s <= 1 THEN 0 WHEN s <= 2 THEN 1 WHEN s <= 3 THEN 2 WHEN s <= 5 THEN 3
             WHEN s <= 8 THEN 4 WHEN s <= 13 THEN 5 WHEN s <= 21 THEN 6 WHEN s <= 34 THEN 7
             WHEN s <= 55 THEN 8 WHEN s <= 89 THEN 9 ELSE 10
           END AS balde,
           count(*) AS n,
           sum((s * 1000)::bigint) AS soma_ms
    FROM (
        SELECT r.timestamp, EXTRACT(EPOCH FROM (r.timestamp - p.timestamp)) AS s
        FROM messages r
        JOIN messages p ON p.id = r.responde_a AND p.tenant_id = r.tenant_id
        WHERE r.tenant_id = :t AND r.remetente = 'agente'
          AND r.timestamp >= :desde AND r.timestamp < :ate
    ) r
    GROUP BY 1, 2
    """.replace("r.timestamp\n", "timestamp\n")
)
SQL_ULTIMA_MENSAGEM = text(
    "SELECT timestamp, remetente FROM messages WHERE tenant_id = :t ORDER BY timestamp DESC LIMIT 1"
)
SQL_CONVERSAS_POR_STATUS = text(
    "SELECT status, count(*) AS total FROM conversations WHERE tenant_id = :t GROUP BY status"
)
SQL_DOCUMENTOS = text(
    "SELECT count(*) AS documentos, coalesce(sum(num_trechos), 0) AS trechos "
    "FROM knowledge_documents WHERE tenant_id = :t"
)


# --- Cálculo e gravação -------------------------------------------------------------------------


def _linha_vazia() -> dict[str, Any]:
    return {
        "msgs_lead": 0,
        "msgs_agente": 0,
        "msgs_humano": 0,
        "msgs_nao_texto": 0,
        "conversas_iniciadas": 0,
        "handoffs": 0,
        "handoffs_resolvidos": 0,
        "bloqueios_guardrail": 0,
        "falhas_envio": 0,
        "resp_n": 0,
        "resp_soma_ms": 0,
        "resp_hist": [0] * TAMANHO_HISTOGRAMA,
        "intencoes": {},
        "tokens_entrada": 0,
        "tokens_saida": 0,
        "custo_usd": Decimal(0),
        "custo_roteador": Decimal(0),
        "custo_suporte": Decimal(0),
        "custo_embedding": Decimal(0),
        "custo_por_modelo": {},
    }


async def calcular_horas(
    session: AsyncSession, tenant_id: uuid.UUID, desde: datetime, ate: datetime
) -> dict[datetime, dict[str, Any]]:
    """Linhas por hora da janela `[desde, ate)`; só aparecem as horas com alguma atividade."""
    horas: dict[datetime, dict[str, Any]] = defaultdict(_linha_vazia)
    parametros = {"t": tenant_id, "desde": desde, "ate": ate}

    for r in (await session.execute(SQL_MENSAGENS, parametros)).all():
        linha = horas[r.hora]
        linha.update(
            msgs_lead=r.msgs_lead,
            msgs_agente=r.msgs_agente,
            msgs_humano=r.msgs_humano,
            msgs_nao_texto=r.msgs_nao_texto,
            falhas_envio=r.falhas_envio,
        )
    for r in (await session.execute(SQL_INTENCOES, parametros)).all():
        horas[r.hora]["intencoes"][r.intencao] = int(r.total)
    for r in (await session.execute(SQL_CONVERSAS, parametros)).all():
        horas[r.hora]["conversas_iniciadas"] = int(r.total)
    for r in (
        await session.execute(
            SQL_HANDOFFS, {**parametros, "nao_guardrail": list(NAO_SAO_GUARDRAIL)}
        )
    ).all():
        horas[r.hora]["handoffs"] = int(r.handoffs)
        horas[r.hora]["handoffs_resolvidos"] = int(r.resolvidos)
        horas[r.hora]["bloqueios_guardrail"] = int(r.bloqueios)
    for r in (await session.execute(SQL_LLM, parametros)).all():
        horas[r.hora].update(
            tokens_entrada=int(r.tokens_entrada),
            tokens_saida=int(r.tokens_saida),
            custo_usd=Decimal(r.custo),
            custo_roteador=Decimal(r.custo_roteador),
            custo_suporte=Decimal(r.custo_suporte),
            custo_embedding=Decimal(r.custo_embedding),
        )
    for r in (await session.execute(SQL_LLM_MODELO, parametros)).all():
        horas[r.hora]["custo_por_modelo"][r.modelo] = float(r.custo)
    for r in (await session.execute(SQL_RESPOSTA, parametros)).all():
        linha = horas[r.hora]
        linha["resp_n"] += int(r.n)
        linha["resp_soma_ms"] += int(r.soma_ms)
        linha["resp_hist"][int(r.balde)] += int(r.n)
    return dict(horas)


_INSERIR_HORA = text(
    """
    INSERT INTO painel_agregado_hora (
        tenant_id, hora, msgs_lead, msgs_agente, msgs_humano, msgs_nao_texto, conversas_iniciadas,
        handoffs, handoffs_resolvidos, bloqueios_guardrail, falhas_envio, resp_n, resp_soma_ms, resp_hist, intencoes,
        tokens_entrada, tokens_saida, custo_usd, custo_roteador, custo_suporte, custo_embedding,
        custo_por_modelo, atualizado_em
    ) VALUES (
        :tenant_id, :hora, :msgs_lead, :msgs_agente, :msgs_humano, :msgs_nao_texto,
        :conversas_iniciadas, :handoffs, :handoffs_resolvidos, :bloqueios_guardrail, :falhas_envio, :resp_n, :resp_soma_ms,
        CAST(:resp_hist AS jsonb), CAST(:intencoes AS jsonb), :tokens_entrada, :tokens_saida,
        :custo_usd, :custo_roteador, :custo_suporte, :custo_embedding,
        CAST(:custo_por_modelo AS jsonb), now()
    )
    ON CONFLICT (tenant_id, hora) DO UPDATE SET
        msgs_lead = EXCLUDED.msgs_lead, msgs_agente = EXCLUDED.msgs_agente,
        msgs_humano = EXCLUDED.msgs_humano, msgs_nao_texto = EXCLUDED.msgs_nao_texto,
        conversas_iniciadas = EXCLUDED.conversas_iniciadas, handoffs = EXCLUDED.handoffs,
        handoffs_resolvidos = EXCLUDED.handoffs_resolvidos,
        bloqueios_guardrail = EXCLUDED.bloqueios_guardrail, falhas_envio = EXCLUDED.falhas_envio,
        resp_n = EXCLUDED.resp_n, resp_soma_ms = EXCLUDED.resp_soma_ms,
        resp_hist = EXCLUDED.resp_hist, intencoes = EXCLUDED.intencoes,
        tokens_entrada = EXCLUDED.tokens_entrada, tokens_saida = EXCLUDED.tokens_saida,
        custo_usd = EXCLUDED.custo_usd, custo_roteador = EXCLUDED.custo_roteador,
        custo_suporte = EXCLUDED.custo_suporte, custo_embedding = EXCLUDED.custo_embedding,
        custo_por_modelo = EXCLUDED.custo_por_modelo, atualizado_em = now()
    """
)


async def recalcular_empresa(
    tenant_id: uuid.UUID, desde: datetime, ate: datetime
) -> tuple[int, int]:
    """Regrava `[desde, ate)` da empresa e a situação corrente. Devolve `(horas_gravadas, mensagens)`.

    `desde` e `ate` são alinhados à hora cheia. Repetir com a mesma janela dá o mesmo resultado.
    """
    desde = inicio_da_hora(desde)
    ate = inicio_da_hora(ate) + timedelta(hours=1)
    async with tenant_session(tenant_id) as s:
        horas = await calcular_horas(s, tenant_id, desde, ate)
        await s.execute(
            text(
                "DELETE FROM painel_agregado_hora "
                "WHERE tenant_id = :t AND hora >= :desde AND hora < :ate"
            ),
            {"t": tenant_id, "desde": desde, "ate": ate},
        )
        for hora, linha in sorted(horas.items()):
            await s.execute(
                _INSERIR_HORA,
                {
                    **linha,
                    "tenant_id": tenant_id,
                    "hora": hora,
                    "resp_hist": json.dumps(linha["resp_hist"]),
                    "intencoes": json.dumps(linha["intencoes"]),
                    "custo_por_modelo": json.dumps(linha["custo_por_modelo"]),
                },
            )
        await _gravar_situacao(s, tenant_id)
    mensagens = sum(
        int(h["msgs_lead"]) + int(h["msgs_agente"]) + int(h["msgs_humano"]) for h in horas.values()
    )
    return len(horas), mensagens


async def _gravar_situacao(s: AsyncSession, tenant_id: uuid.UUID) -> None:
    ultima = (await s.execute(SQL_ULTIMA_MENSAGEM, {"t": tenant_id})).first()
    por_status = {
        r.status: int(r.total)
        for r in (await s.execute(SQL_CONVERSAS_POR_STATUS, {"t": tenant_id})).all()
    }
    docs = (await s.execute(SQL_DOCUMENTOS, {"t": tenant_id})).one()
    await s.execute(
        text(
            """
            INSERT INTO painel_situacao (
                tenant_id, ultima_mensagem_em, ultimo_remetente, conversas_abertas,
                conversas_handoff, documentos, trechos, atualizado_em
            ) VALUES (:t, :em, :quem, :abertas, :handoff, :docs, :trechos, now())
            ON CONFLICT (tenant_id) DO UPDATE SET
                ultima_mensagem_em = EXCLUDED.ultima_mensagem_em,
                ultimo_remetente = EXCLUDED.ultimo_remetente,
                conversas_abertas = EXCLUDED.conversas_abertas,
                conversas_handoff = EXCLUDED.conversas_handoff,
                documentos = EXCLUDED.documentos, trechos = EXCLUDED.trechos, atualizado_em = now()
            """
        ),
        {
            "t": tenant_id,
            "em": ultima.timestamp if ultima else None,
            "quem": ultima.remetente if ultima else None,
            "abertas": por_status.get("aberta", 0),
            "handoff": por_status.get("handoff", 0),
            "docs": int(docs.documentos),
            "trechos": int(docs.trechos),
        },
    )


RETENCAO_DIAS: Final = 400


async def apagar_antigas(tenant_id: uuid.UUID, antes: datetime) -> None:
    """Remove as linhas horárias da empresa anteriores a `antes` (retenção, research R-18)."""
    async with tenant_session(tenant_id) as s:
        await s.execute(
            text("DELETE FROM painel_agregado_hora WHERE tenant_id = :t AND hora < :antes"),
            {"t": tenant_id, "antes": antes},
        )


class ResultadoAgregacao:
    """Resumo de uma execução do job (vai para o log, sem dado de cliente)."""

    def __init__(self) -> None:
        self.empresas = 0
        self.horas = 0
        self.falhas: list[str] = []
        self.segundos = 0.0


async def _empresas_com_dados() -> list[uuid.UUID]:
    """Empresas cujos dados existem (as já apagadas ficam de fora). Leitura pelo papel do painel."""
    async with painel_session() as s:
        linhas = await s.execute(
            select(Tenant.id).where(Tenant.dados_apagados_em.is_(None)).order_by(Tenant.slug)
        )
        return list(linhas.scalars())


async def recalcular_todas(
    *,
    agora: datetime | None = None,
    janela_horas: int = JANELA_PADRAO_HORAS,
    retencao_dias: int | None = None,
) -> ResultadoAgregacao:
    """Percorre as empresas uma a uma. A falha de uma não impede as outras (fica em `falhas`)."""
    inicio = time.perf_counter()
    resultado = ResultadoAgregacao()
    agora = agora or datetime.now(UTC)
    desde = agora - timedelta(hours=janela_horas)
    for tenant_id in await _empresas_com_dados():
        try:
            horas, _ = await recalcular_empresa(tenant_id, desde, agora)
            if retencao_dias is not None:
                await apagar_antigas(tenant_id, agora - timedelta(days=retencao_dias))
        except Exception as exc:  # noqa: BLE001 - uma empresa com erro não derruba as demais
            resultado.falhas.append(f"{tenant_id}: {type(exc).__name__}")
            logger.exception(
                "falha ao agregar empresa", extra={"dados": {"tenant_id": str(tenant_id)}}
            )
            continue
        resultado.empresas += 1
        resultado.horas += horas
    resultado.segundos = time.perf_counter() - inicio
    logger.info(
        "agregacao do painel concluida",
        extra={
            "dados": {
                "empresas": resultado.empresas,
                "horas": resultado.horas,
                "falhas": len(resultado.falhas),
                "segundos": round(resultado.segundos, 3),
            }
        },
    )
    return resultado
