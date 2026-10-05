"""Tipos de entrada, configuração e decisão do orquestrador."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from agents.support.agent import RespostaSuporte
from core.rag.retrieve import Trecho
from db.models import TenantConfig
from db.repositories import Turno


@dataclass(frozen=True)
class EntradaMensagem:
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID | None  # None em avaliações offline (sem conversa no banco)
    message_id: uuid.UUID | None
    conteudo: str
    tipo: str  # texto | nao_texto
    historico: list[Turno] = field(default_factory=list)


@dataclass(frozen=True)
class ConfigTenant:
    """Subconjunto de `tenant_config` usado pelo grafo."""

    tom_de_voz: str = ""
    horario_funcionamento: dict[str, str] = field(default_factory=dict)
    palavras_gatilho: list[str] = field(default_factory=list)
    topicos_proibidos: list[str] = field(default_factory=list)
    limite_desconto_percentual: float = 0.0
    confianca_minima_handoff: float = 0.7
    router_confidence_threshold: float = 0.6
    min_similarity: float = 0.30

    @classmethod
    def de_modelo(cls, c: TenantConfig) -> ConfigTenant:
        return cls(
            tom_de_voz=c.tom_de_voz,
            horario_funcionamento=c.horario_funcionamento,
            palavras_gatilho=c.palavras_gatilho,
            topicos_proibidos=c.topicos_proibidos,
            limite_desconto_percentual=c.limite_desconto_percentual,
            confianca_minima_handoff=c.confianca_minima_handoff,
            router_confidence_threshold=c.router_confidence_threshold,
            min_similarity=c.min_similarity,
        )


@dataclass(frozen=True)
class Decisao:
    """Resultado final do grafo para uma mensagem."""

    acao: Literal["responder", "handoff"]
    texto: str
    motivo: str | None = None
    intencao: str | None = None
    intencao_confianca: float | None = None
    intencoes_secundarias: list[str] = field(default_factory=list)
    confianca: float = 0.0


class EstadoGrafo(TypedDict, total=False):
    entrada: EntradaMensagem
    config: ConfigTenant
    intencao: str
    intencao_confianca: float
    intencoes_secundarias: list[str]
    trechos: list[Trecho]
    resposta: RespostaSuporte
    decisao: Decisao
    extras: dict[str, Any]
