"""Ficha da empresa no painel (spec 004, US2): identificação, conexão, prontidão, atendimento, custo, auditoria.

Lê pelo papel `plantao_painel`, sempre filtrando por `tenant_id`. Credenciais aparecem só como "configuradas";
a auditoria já traz a marca `<atualizada>` no lugar de qualquer valor secreto; nada de texto de mensagem nem
contato (ADR-0006).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.painel import planos
from core.painel.agregacao import media_ms, p95_s, somar_histogramas
from core.painel.consultas import (
    _atualizado_em,
    _f,
    _i,
    _iso,
    _item,
    _somas,
    janela,
    serie_do_periodo,
)
from core.tenancy.ciclo_vida import TRANSICOES, Estado
from core.tenancy.config import CAMPOS_CONFIG
from db.painel import painel_session

__all__ = [
    "EmpresaInexistente",
    "auditoria",
    "configuracao",
    "ficha",
    "serie_da_empresa",
]

ROTULOS_DE_ACAO: Final = {
    Estado.SUSPENSO: "Suspender",
    Estado.ENCERRADO: "Encerrar",
}
ITENS_DE_PRONTIDAO: Final = (
    ("config", "Configuração mínima preenchida", "config_ok"),
    ("documentos", "Documentos da base de conhecimento enviados", "documentos_ok"),
    ("conexao", "Conexão do canal verificada", "conexao_ok"),
    ("conversa_teste", "Conversa de teste aprovada", "conversa_teste_ok"),
)

_SQL_EMPRESA = text(
    """
    SELECT t.id, t.slug, t.nome_empresa, t.nicho, t.plano, t.status, t.criado_em, t.ativado_em,
           t.encerrado_em, t.dados_apagados_em, t.versao,
           s.ultima_mensagem_em, s.ultimo_remetente, s.conversas_abertas, s.conversas_handoff,
           s.documentos, s.trechos, s.atualizado_em AS situacao_em,
           c.canal, c.provedor, c.instance_name, c.verificada_em
    FROM tenants t
    LEFT JOIN painel_situacao s ON s.tenant_id = t.id
    LEFT JOIN channel_connections c ON c.tenant_id = t.id AND c.canal = 'whatsapp'
    WHERE t.slug = :slug
    """
)
_SQL_PRONTIDAO = text(
    "SELECT tipo, executado_em, operador, aprovado, config_ok, documentos_ok, conexao_ok, conversa_teste_ok "
    "FROM readiness_checks WHERE tenant_id = :t AND tipo = :tipo ORDER BY executado_em DESC LIMIT 1"
)
_SQL_HORAS = text(
    """
    SELECT msgs_lead, msgs_agente, msgs_humano, msgs_nao_texto, handoffs, bloqueios_guardrail, falhas_envio,
           resp_n, resp_soma_ms, resp_hist, intencoes, tokens_entrada, tokens_saida, custo_usd,
           custo_roteador, custo_suporte, custo_embedding, custo_por_modelo
    FROM painel_agregado_hora
    WHERE tenant_id = :t AND hora >= :ini AND hora < :fim
    """
)
_SQL_CONVERSAS_STATUS = text(
    "SELECT status, canal, count(*) AS total FROM conversations "
    "WHERE tenant_id = :t AND iniciado_em >= :ini AND iniciado_em < :fim GROUP BY status, canal"
)
_SQL_MOTIVOS = text(
    "SELECT motivo, count(*) AS total FROM handoff_log "
    "WHERE tenant_id = :t AND criado_em >= :ini AND criado_em < :fim "
    "GROUP BY motivo ORDER BY total DESC, motivo LIMIT 10"
)


class EmpresaInexistente(LookupError):
    """Nenhuma empresa com o `slug` informado."""


async def _linha_da_empresa(s: AsyncSession, slug: str) -> dict[str, Any]:
    linha = (await s.execute(_SQL_EMPRESA, {"slug": slug})).mappings().first()
    if linha is None:
        raise EmpresaInexistente(slug)
    return dict(linha)


def _acoes(estado: str) -> list[dict[str, str]]:
    acoes: list[dict[str, str]] = []
    for destino in TRANSICOES[Estado(estado)]:
        if destino is Estado.ATIVO:
            rotulo = "Retomar" if estado == Estado.SUSPENSO.value else "Ativar"
        else:
            rotulo = ROTULOS_DE_ACAO[destino]
        acoes.append({"para": destino.value, "rotulo": rotulo})
    return acoes


async def _prontidao(
    s: AsyncSession, tenant_id: uuid.UUID
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    pront = (
        (await s.execute(_SQL_PRONTIDAO, {"t": tenant_id, "tipo": "prontidao"})).mappings().first()
    )
    teste = (
        (await s.execute(_SQL_PRONTIDAO, {"t": tenant_id, "tipo": "conversa_teste"}))
        .mappings()
        .first()
    )
    resultado_pront = None
    if pront is not None:
        resultado_pront = {
            "aprovada": bool(pront["aprovado"]),
            "executada_em": _iso(pront["executado_em"]),
            "operador": pront["operador"],
            "itens": [
                {"id": ident, "ok": bool(pront[coluna]), "rotulo": rotulo}
                for ident, rotulo, coluna in ITENS_DE_PRONTIDAO
            ],
        }
    resultado_teste = None
    if teste is not None:
        resultado_teste = {
            "aprovado": bool(teste["aprovado"]),
            "executado_em": _iso(teste["executado_em"]),
            "operador": teste["operador"],
        }
    return resultado_pront, resultado_teste


async def _atendimento_e_custo(
    s: AsyncSession, tenant_id: uuid.UUID, j: Any, plano: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    horas = [
        dict(r)
        for r in (await s.execute(_SQL_HORAS, {"t": tenant_id, "ini": j.inicio, "fim": j.fim}))
        .mappings()
        .all()
    ]

    def soma(campo: str) -> float:
        return sum(_f(h[campo]) for h in horas)

    intencoes: dict[str, int] = {}
    por_modelo: dict[str, float] = {}
    for h in horas:
        for chave, valor in (h["intencoes"] or {}).items():
            intencoes[chave] = intencoes.get(chave, 0) + int(valor)
        for modelo, valor in (h["custo_por_modelo"] or {}).items():
            por_modelo[modelo] = round(por_modelo.get(modelo, 0.0) + float(valor), 6)
    hist = somar_histogramas(h["resp_hist"] or [] for h in horas)

    status = (
        await s.execute(_SQL_CONVERSAS_STATUS, {"t": tenant_id, "ini": j.inicio, "fim": j.fim})
    ).all()
    conversas: dict[str, Any] = {"abertas": 0, "handoff": 0, "resolvidas": 0, "por_canal": {}}
    total_conversas = 0
    for linha in status:
        total = int(linha.total)
        total_conversas += total
        chave = {"aberta": "abertas", "handoff": "handoff", "resolvida": "resolvidas"}.get(
            linha.status
        )
        if chave:
            conversas[chave] += total
        conversas["por_canal"][linha.canal] = conversas["por_canal"].get(linha.canal, 0) + total
    motivos = [
        {"motivo": r.motivo, "total": int(r.total)}
        for r in (
            await s.execute(_SQL_MOTIVOS, {"t": tenant_id, "ini": j.inicio, "fim": j.fim})
        ).all()
    ]
    handoffs = soma("handoffs")
    media = media_ms(int(soma("resp_n")), int(soma("resp_soma_ms")))
    p95 = p95_s(hist)
    atendimento = {
        "mensagens": {
            "lead": int(soma("msgs_lead")),
            "agente": int(soma("msgs_agente")),
            "humano": int(soma("msgs_humano")),
            "nao_texto": int(soma("msgs_nao_texto")),
        },
        "conversas": conversas,
        "taxa_handoff_pct": round(handoffs / total_conversas * 100, 1) if total_conversas else 0.0,
        "motivos_handoff": motivos,
        "resposta_media_s": round(media / 1000, 1) if media is not None else None,
        "resposta_p95_s": p95,
        "intencoes": intencoes,
        "bloqueios_guardrail": int(soma("bloqueios_guardrail")),
        "falhas_envio": int(soma("falhas_envio")),
    }
    custo_total = round(soma("custo_usd"), 4)
    custo = {
        "total_usd": custo_total,
        "tokens_entrada": int(soma("tokens_entrada")),
        "tokens_saida": int(soma("tokens_saida")),
        "por_finalidade": {
            "roteador": round(soma("custo_roteador"), 4),
            "suporte": round(soma("custo_suporte"), 4),
            "embedding": round(soma("custo_embedding"), 4),
        },
        "por_modelo": por_modelo,
        "por_conversa_usd": round(custo_total / total_conversas, 4) if total_conversas else None,
        "preco_plano_usd": planos.preco_do_plano(plano),
    }
    margem = planos.margem_estimada(plano, custo_total, j.dias)
    custo["margem_usd"] = None if margem is None else round(margem, 2)
    return atendimento, custo


async def ficha(slug: str, periodo: str = "30d", agora: datetime | None = None) -> dict[str, Any]:
    """Tudo o que `tenants status` mostra mais o atendimento e o custo do período."""
    agora = (agora or datetime.now(UTC)).astimezone(UTC)
    j = janela(periodo, agora)
    async with painel_session() as s:
        emp = await _linha_da_empresa(s, slug)
        pront, teste = await _prontidao(s, emp["id"])
        somas = (await _somas(s, j)).get(emp["id"])
        apagados = emp["dados_apagados_em"] is not None
        atendimento = custo = None
        if not apagados:
            atendimento, custo = await _atendimento_e_custo(s, emp["id"], j, emp["plano"])
    item = _item(emp, somas or {k: 0 for k in _CHAVES_DE_SOMA}, j, agora)
    pct = item["orcamento_pct"]
    if custo is not None:
        custo["orcamento_usd"] = item["orcamento_usd"]
        custo["orcamento_pct"] = pct
    conexao = None
    if emp["instance_name"] is not None:
        conexao = {
            "canal": emp["canal"],
            "provedor": emp["provedor"],
            "instancia": emp["instance_name"],
            "verificada_em": _iso(emp["verificada_em"]),
            "credenciais": "configuradas",
        }
    return {
        "empresa": {
            "slug": emp["slug"],
            "nome": emp["nome_empresa"],
            "nicho": emp["nicho"],
            "plano": planos.chave_do_plano(emp["plano"]),
            "estado": emp["status"],
            "versao": emp["versao"],
            "criada_em": _iso(emp["criado_em"]),
            "ativada_em": _iso(emp["ativado_em"]),
            "encerrada_em": _iso(emp["encerrado_em"]),
            "dados_apagados_em": _iso(emp["dados_apagados_em"]),
        },
        "acoes_permitidas": _acoes(emp["status"]),
        "conexao": conexao,
        "base": None
        if apagados
        else {"documentos": _i(emp["documentos"]), "trechos": _i(emp["trechos"])},
        "prontidao": pront,
        "ultimo_teste": teste,
        "atendimento": atendimento,
        "custo": custo,
        "atencao": item["atencao"],
        "periodo": periodo,
        "atualizado_em": _atualizado_em([emp]),
    }


_CHAVES_DE_SOMA: Final = (
    "lead agente humano conversas handoffs resolvidos falhas custo tokens a_lead a_agente a_humano "
    "a_conversas a_handoffs a_custo custo_30d"
).split()


async def serie_da_empresa(
    slug: str, periodo: str, agora: datetime | None = None
) -> dict[str, Any]:
    j = janela(periodo, agora)
    async with painel_session() as s:
        emp = await _linha_da_empresa(s, slug)
        pontos = [] if emp["dados_apagados_em"] else await serie_do_periodo(s, j, emp["id"])
    return {"periodo": periodo, "fuso": "America/Sao_Paulo", "pontos": pontos}


async def configuracao(slug: str) -> dict[str, Any]:
    async with painel_session() as s:
        emp = await _linha_da_empresa(s, slug)
        colunas = ", ".join(CAMPOS_CONFIG)  # nomes vêm do modelo, nunca do operador
        linha = (
            (
                await s.execute(
                    text(f"SELECT {colunas} FROM tenant_config WHERE tenant_id = :t"),
                    {"t": emp["id"]},
                )
            )
            .mappings()
            .first()
        )
    return {
        "versao": emp["versao"],
        "estado": emp["status"],
        "configuracao": dict(linha) if linha else None,
    }


async def auditoria(slug: str, pagina: int = 1, tamanho: int = 20) -> dict[str, Any]:
    async with painel_session() as s:
        emp = await _linha_da_empresa(s, slug)
        total = (
            await s.execute(
                text("SELECT count(*) FROM audit_log WHERE tenant_id = :t"), {"t": emp["id"]}
            )
        ).scalar_one()
        linhas = (
            (
                await s.execute(
                    text(
                        "SELECT criado_em, entidade, campo, valor_anterior, valor_novo, operador FROM audit_log "
                        "WHERE tenant_id = :t ORDER BY criado_em DESC, id LIMIT :n OFFSET :o"
                    ),
                    {"t": emp["id"], "n": tamanho, "o": (pagina - 1) * tamanho},
                )
            )
            .mappings()
            .all()
        )
    return {
        "total": int(total),
        "pagina": pagina,
        "tamanho": tamanho,
        "itens": [
            {
                "criado_em": _iso(r["criado_em"]),
                "entidade": r["entidade"],
                "campo": r["campo"],
                "valor_anterior": r["valor_anterior"],
                "valor_novo": r["valor_novo"],
                "operador": r["operador"],
            }
            for r in linhas
        ],
    }
