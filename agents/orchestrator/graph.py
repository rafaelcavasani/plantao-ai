"""Grafo do orquestrador (LangGraph): entrada -> roteador -> suporte -> guardrails de saída -> resposta.

Qualquer falha ou reprovação em um nó termina o grafo com uma `Decisao` de handoff; nada chega ao
cliente sem passar pelos guardrails de saída (princípio V).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.orchestrator.state import ConfigTenant, Decisao, EntradaMensagem, EstadoGrafo
from agents.router.agent import classificar
from agents.router.schemas import Intencao
from agents.support.agent import responder
from core.config import settings
from core.guardrails import ConfigGuardrails, checar_entrada, checar_saida
from core.handoff.textos import texto_para_motivo
from core.llm.ports import LLMClient, LLMError, SaidaInvalida
from core.rag.retrieve import Trecho, buscar_trechos

logger = logging.getLogger("plantao.orchestrator")

Buscar = Callable[..., Awaitable[list[Trecho]]]


def _handoff(estado: EstadoGrafo, motivo: str, confianca: float = 0.0) -> EstadoGrafo:
    decisao = Decisao(
        acao="handoff",
        texto=texto_para_motivo(motivo),
        motivo=motivo,
        intencao=estado.get("intencao"),
        intencao_confianca=estado.get("intencao_confianca"),
        intencoes_secundarias=estado.get("intencoes_secundarias", []),
        confianca=confianca,
    )
    logger.info("handoff", extra={"dados": {"motivo": motivo}})
    return {"decisao": decisao}


def _seguir(proximo: str) -> Callable[[EstadoGrafo], str]:
    """Aresta condicional: termina se algum nó já produziu a decisão final."""

    def decidir(estado: EstadoGrafo) -> str:
        return END if "decisao" in estado else proximo

    return decidir


class Grafo:
    def __init__(
        self,
        llm: LLMClient,
        *,
        buscar: Buscar = buscar_trechos,
        modelo_roteador: str | None = None,
        modelo_suporte: str | None = None,
    ) -> None:
        self._llm = llm
        self._buscar = buscar
        self._modelo_roteador = modelo_roteador or settings.model_cheap
        self._modelo_suporte = modelo_suporte or settings.model_strong
        self._grafo = self._montar()

    # nós ---------------------------------------------------------------------------------------
    async def _no_entrada(self, estado: EstadoGrafo) -> EstadoGrafo:
        entrada, config = estado["entrada"], estado["config"]
        resultado = checar_entrada(entrada.conteudo, entrada.tipo, config.palavras_gatilho)
        if resultado.aprovado:
            return {}
        return _handoff(estado, resultado.motivo or "entrada_reprovada")

    async def _no_roteador(self, estado: EstadoGrafo) -> EstadoGrafo:
        entrada, config = estado["entrada"], estado["config"]
        try:
            saida = await classificar(
                self._llm,
                mensagem=entrada.conteudo,
                historico=entrada.historico,
                modelo=self._modelo_roteador,
                tenant_id=entrada.tenant_id,
                conversation_id=entrada.conversation_id,
                message_id=entrada.message_id,
            )
        except (LLMError, SaidaInvalida):
            return _handoff(estado, "falha_llm")
        registro: EstadoGrafo = {
            "intencao": saida.intencao.value,
            "intencao_confianca": saida.confianca,
            "intencoes_secundarias": [i.value for i in saida.intencoes_secundarias],
        }
        efetiva = (
            Intencao.SUPORTE
            if saida.confianca < config.router_confidence_threshold
            else saida.intencao
        )
        if efetiva != Intencao.SUPORTE:
            registro.update(
                _handoff({**estado, **registro}, f"intencao_sem_agente:{efetiva.value}")
            )
        return registro

    async def _no_suporte(self, estado: EstadoGrafo) -> EstadoGrafo:
        entrada, config = estado["entrada"], estado["config"]
        try:
            trechos = await self._buscar(
                self._llm,
                tenant_id=entrada.tenant_id,
                pergunta=entrada.conteudo,
                min_similarity=config.min_similarity,
                conversation_id=entrada.conversation_id,
                message_id=entrada.message_id,
            )
        except LLMError:
            return _handoff(estado, "falha_embedding")
        if not trechos:
            return _handoff(estado, "sem_resposta_na_base")
        try:
            resposta = await responder(
                self._llm,
                pergunta=entrada.conteudo,
                historico=entrada.historico,
                trechos=trechos,
                tom_de_voz=config.tom_de_voz,
                horario_funcionamento=config.horario_funcionamento,
                modelo=self._modelo_suporte,
                tenant_id=entrada.tenant_id,
                conversation_id=entrada.conversation_id,
                message_id=entrada.message_id,
            )
        except (LLMError, SaidaInvalida):
            return _handoff(estado, "falha_llm")
        if not resposta.responde:
            return _handoff(estado, "sem_resposta_na_base", resposta.confianca)
        return {"trechos": trechos, "resposta": resposta}

    async def _no_guardrails_saida(self, estado: EstadoGrafo) -> EstadoGrafo:
        config, resposta = estado["config"], estado["resposta"]
        resultado = checar_saida(
            resposta.resposta,
            [t.texto for t in estado["trechos"]],
            resposta.confianca,
            ConfigGuardrails(
                confianca_minima=config.confianca_minima_handoff,
                topicos_proibidos=config.topicos_proibidos,
                limite_desconto_percentual=config.limite_desconto_percentual,
            ),
        )
        if not resultado.aprovado:
            return _handoff(estado, resultado.motivo or "saida_reprovada", resposta.confianca)
        return {}

    async def _no_responder(self, estado: EstadoGrafo) -> EstadoGrafo:
        resposta = estado["resposta"]
        return {
            "decisao": Decisao(
                acao="responder",
                texto=resposta.resposta,
                intencao=estado.get("intencao"),
                intencao_confianca=estado.get("intencao_confianca"),
                intencoes_secundarias=estado.get("intencoes_secundarias", []),
                confianca=resposta.confianca,
            )
        }

    # montagem ----------------------------------------------------------------------------------
    def _montar(self) -> Any:
        # `Any`: os overloads de `add_node` do LangGraph não aceitam TypedDict com campos de dataclass.
        g: Any = StateGraph(EstadoGrafo)
        g.add_node("entrada", self._no_entrada)
        g.add_node("roteador", self._no_roteador)
        g.add_node("suporte", self._no_suporte)
        g.add_node("guardrails_saida", self._no_guardrails_saida)
        g.add_node("responder", self._no_responder)
        g.add_edge(START, "entrada")
        g.add_conditional_edges("entrada", _seguir("roteador"), ["roteador", END])
        g.add_conditional_edges("roteador", _seguir("suporte"), ["suporte", END])
        g.add_conditional_edges("suporte", _seguir("guardrails_saida"), ["guardrails_saida", END])
        g.add_conditional_edges("guardrails_saida", _seguir("responder"), ["responder", END])
        g.add_edge("responder", END)
        return g.compile()

    async def executar(self, entrada: EntradaMensagem, config: ConfigTenant) -> Decisao:
        final = await self._grafo.ainvoke({"entrada": entrada, "config": config})
        decisao: Decisao = final["decisao"]
        return decisao


def build_graph(llm: LLMClient, **kwargs: Any) -> Grafo:
    return Grafo(llm, **kwargs)
