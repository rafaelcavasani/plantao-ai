"""Conversas da empresa só por metadados (spec 004, US5, FR-005; ADR-0006).

O painel nunca mostra o texto das mensagens nem o contato, nem mascarado: o papel `plantao_painel` não tem
privilégio sobre `messages.conteudo` nem sobre `conversations.contato_*`. As consultas abaixo listam as colunas
uma a uma (nunca `SELECT *`) para que o contrato continue valendo se alguém ampliar os privilégios por engano.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

from core.painel.consultas import _iso
from core.painel.ficha import EmpresaInexistente, _linha_da_empresa
from db.painel import painel_session

__all__ = ["EmpresaInexistente", "ConversaInexistente", "conversa", "listar_conversas"]

LIMITE_DA_LINHA_DO_TEMPO = 500


class ConversaInexistente(LookupError):
    """Nenhuma conversa com esse identificador na empresa."""


_SQL_LISTA = text(
    """
    SELECT c.id, c.canal, c.status, c.agente_atual, c.iniciado_em, c.ultima_atividade_em,
           (SELECT count(*) FROM messages m
             WHERE m.conversation_id = c.id AND m.tenant_id = c.tenant_id) AS total_mensagens
    FROM conversations c
    WHERE c.tenant_id = :t
    ORDER BY c.ultima_atividade_em DESC, c.id
    LIMIT :n OFFSET :o
    """
)
_SQL_CONVERSA = text(
    "SELECT id, canal, status, agente_atual, iniciado_em, ultima_atividade_em, handoff_em, iniciada_por "
    "FROM conversations WHERE tenant_id = :t AND id = :c"
)
_SQL_HANDOFF = text(
    "SELECT motivo, confianca_no_momento, criado_em FROM handoff_log "
    "WHERE tenant_id = :t AND conversation_id = :c ORDER BY criado_em DESC LIMIT 1"
)
_SQL_LINHA_DO_TEMPO = text(
    """
    SELECT remetente, tipo, timestamp, intencao, intencao_confianca, status_envio
    FROM messages WHERE tenant_id = :t AND conversation_id = :c
    ORDER BY timestamp, id LIMIT :limite
    """
)


def _id_curto(valor: uuid.UUID) -> str:
    return str(valor)[:8]


async def listar_conversas(slug: str, pagina: int = 1, tamanho: int = 20) -> dict[str, Any]:
    async with painel_session() as s:
        emp = await _linha_da_empresa(s, slug)
        total = (
            await s.execute(
                text("SELECT count(*) FROM conversations WHERE tenant_id = :t"), {"t": emp["id"]}
            )
        ).scalar_one()
        linhas = (
            (
                await s.execute(
                    _SQL_LISTA, {"t": emp["id"], "n": tamanho, "o": (pagina - 1) * tamanho}
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
                "id_curto": _id_curto(r["id"]),
                "id": str(r["id"]),
                "canal": r["canal"],
                "status": r["status"],
                "agente_atual": r["agente_atual"],
                "iniciada_em": _iso(r["iniciado_em"]),
                "ultima_atividade_em": _iso(r["ultima_atividade_em"]),
                "total_mensagens": int(r["total_mensagens"]),
            }
            for r in linhas
        ],
    }


async def conversa(slug: str, conversa_id: uuid.UUID) -> dict[str, Any]:
    async with painel_session() as s:
        emp = await _linha_da_empresa(s, slug)
        c = (await s.execute(_SQL_CONVERSA, {"t": emp["id"], "c": conversa_id})).mappings().first()
        if c is None:
            raise ConversaInexistente(str(conversa_id))
        handoff = (
            (await s.execute(_SQL_HANDOFF, {"t": emp["id"], "c": conversa_id})).mappings().first()
        )
        linha = (
            (
                await s.execute(
                    _SQL_LINHA_DO_TEMPO,
                    {"t": emp["id"], "c": conversa_id, "limite": LIMITE_DA_LINHA_DO_TEMPO},
                )
            )
            .mappings()
            .all()
        )
    return {
        "id_curto": _id_curto(c["id"]),
        "id": str(c["id"]),
        "canal": c["canal"],
        "status": c["status"],
        "agente_atual": c["agente_atual"],
        "iniciada_por": c["iniciada_por"],
        "iniciada_em": _iso(c["iniciado_em"]),
        "ultima_atividade_em": _iso(c["ultima_atividade_em"]),
        "total_mensagens": len(linha),
        "handoff": (
            {
                "motivo": handoff["motivo"],
                "confianca": float(handoff["confianca_no_momento"]),
                "em": _iso(handoff["criado_em"]),
            }
            if handoff
            else None
        ),
        "linha_do_tempo": [
            {
                "remetente": m["remetente"],
                "tipo": m["tipo"],
                "em": _iso(m["timestamp"]),
                "intencao": m["intencao"],
                "intencao_confianca": m["intencao_confianca"],
                "status_envio": m["status_envio"],
            }
            for m in linha
        ],
    }
