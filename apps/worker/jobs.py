"""Job principal: processa uma mensagem do lead e responde (ou repassa a um humano).

Quatro fases, para nunca segurar transação de banco durante chamadas externas (R-05):
1. ler (transação curta); 2. executar o grafo (sem transação); 3. gravar decisão e resposta com
`status_envio = pendente`; 4. enviar e atualizar `status_envio`.

Idempotência: o índice único em `messages.responde_a` impede duas respostas à mesma mensagem, mesmo
com reentrega do ARQ ou jobs concorrentes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from agents.orchestrator.graph import Grafo
from agents.orchestrator.state import ConfigTenant, Decisao, EntradaMensagem
from core.handoff.service import registrar_handoff
from core.handoff.textos import MOTIVO_FALHA_CANAL
from core.observability.logging import definir_contexto, limpar_contexto
from core.painel.agregacao import JANELA_PADRAO_HORAS, RETENCAO_DIAS, recalcular_todas
from core.painel.remessas import processar_remessa
from core.ports.channel import ChannelError, MessageChannel
from core.security.crypto import get_cripto
from core.tenancy import ConexaoAusente, carregar_conexao_canal
from core.tenancy.ciclo_vida import Estado
from db.models import Conversation, Message
from db.repositories import (
    agora,
    carregar_config,
    carregar_estado_empresa,
    carregar_historico,
    resposta_existente,
    travar_estado_compartilhada,
    ultima_atividade_humana,
)
from db.session import tenant_session

logger = logging.getLogger("plantao.worker")

EMPRESA_INATIVA = "empresa_inativa"


class _EmpresaInativa(Exception):
    """A empresa deixou de estar `ativo` (suspensa, encerrada) antes de a resposta ser gravada."""


def _handoff_expirou(
    handoff_em: datetime | None, ultima_humana: datetime | None, ttl_minutos: int
) -> bool:
    """O handoff expira `ttl_minutos` (config da empresa) após a última atividade humana ou o próprio handoff."""
    referencias = [d for d in (handoff_em, ultima_humana) if d is not None]
    if not referencias:
        return True
    return agora() - max(referencias) >= timedelta(minutes=ttl_minutos)


async def processar_mensagem(
    ctx: dict[str, Any], tenant_id: str, message_id: str, correlation_id: str = ""
) -> str:
    """Devolve um código do resultado: `respondida`, `handoff`, `ja_respondida`, `handoff_ativo`,
    `mensagem_inexistente`, `empresa_inativa`, `falha_canal`. `ctx` traz `grafo` (Grafo) e `channel`."""
    limpar_contexto()
    tid, mid = uuid.UUID(tenant_id), uuid.UUID(message_id)
    definir_contexto(correlation_id=correlation_id, tenant_id=tid)
    grafo: Grafo = ctx["grafo"]
    channel: MessageChannel = ctx["channel"]

    # Fase 1: leitura -------------------------------------------------------------------------
    async with tenant_session(tid) as s:
        if await carregar_estado_empresa(s) != Estado.ATIVO:  # lido do banco, sem cache (R-05)
            logger.info(EMPRESA_INATIVA)
            return EMPRESA_INATIVA
        mensagem = await s.get(Message, mid)
        if mensagem is None:
            logger.warning("mensagem_inexistente")
            return "mensagem_inexistente"
        if await resposta_existente(s, mid) is not None:
            return "ja_respondida"
        conversa = await s.get(Conversation, mensagem.conversation_id)
        assert conversa is not None
        definir_contexto(conversation_id=conversa.id)
        config = ConfigTenant.de_modelo(await carregar_config(s, tid))
        if conversa.status == "handoff":
            humana = await ultima_atividade_humana(s, conversa.id)
            if not _handoff_expirou(conversa.handoff_em, humana, config.handoff_ttl_minutos):
                logger.info("handoff_ativo")
                return "handoff_ativo"
            conversa.status, conversa.agente_atual, conversa.handoff_em = "aberta", "router", None
        entrada = EntradaMensagem(
            tenant_id=tid,
            conversation_id=conversa.id,
            message_id=mid,
            conteudo=mensagem.conteudo,
            tipo=mensagem.tipo,
            historico=await carregar_historico(
                s, conversation_id=conversa.id, antes_de_message_id=mid
            ),
        )
        contato = get_cripto().decrypt(conversa.contato_enc)
        conversa_id = conversa.id

    # Fase 2: grafo (sem transação aberta) ------------------------------------------------------
    decisao = await grafo.executar(entrada, config)

    # Fase 3: gravar decisão e resposta (pendente) -----------------------------------------------
    try:
        resposta_id = await _gravar(tid, mid, conversa_id, decisao)
    except _EmpresaInativa:
        logger.info(EMPRESA_INATIVA)
        return EMPRESA_INATIVA
    except IntegrityError:
        logger.info("ja_respondida_concorrente")
        return "ja_respondida"

    # Fase 4: envio -----------------------------------------------------------------------------
    erro_canal: str | None = None
    try:
        async with tenant_session(tid) as s:
            conexao = await carregar_conexao_canal(s, tid, "whatsapp")
        await channel.send_text(conexao, contato, decisao.texto)
        status_envio = "enviada"
    except ConexaoAusente:
        status_envio, erro_canal = "falha", "conexao_ausente"
    except ChannelError as exc:
        status_envio, erro_canal = "falha", str(exc)
    async with tenant_session(tid) as s:
        await s.execute(
            update(Message).where(Message.id == resposta_id).values(status_envio=status_envio)
        )
        if erro_canal is not None:
            conversa = await s.get(Conversation, conversa_id)
            assert conversa is not None
            await registrar_handoff(
                s,
                tenant_id=tid,
                conversation=conversa,
                message_id=mid,
                motivo=MOTIVO_FALHA_CANAL,
            )
    if erro_canal is not None:
        logger.error("canal_falhou", extra={"dados": {"erro": erro_canal}})
        return MOTIVO_FALHA_CANAL
    return "handoff" if decisao.acao == "handoff" else "respondida"


async def _gravar(
    tenant_id: uuid.UUID, message_id: uuid.UUID, conversation_id: uuid.UUID, decisao: Decisao
) -> uuid.UUID:
    async with tenant_session(tenant_id) as s:
        # Trava compartilhada do estado: uma suspensão em curso espera esta gravação terminar e, depois dela,
        # nenhuma resposta nova é gravada (R-06). O estado é relido já com a trava.
        await travar_estado_compartilhada(s, tenant_id)
        if await carregar_estado_empresa(s) != Estado.ATIVO:
            raise _EmpresaInativa
        mensagem = await s.get(Message, message_id)
        conversa = await s.get(Conversation, conversation_id)
        assert mensagem is not None and conversa is not None
        mensagem.intencao = decisao.intencao
        mensagem.intencao_confianca = decisao.intencao_confianca
        mensagem.intencoes_secundarias = decisao.intencoes_secundarias or None
        if decisao.acao == "handoff":
            await registrar_handoff(
                s,
                tenant_id=tenant_id,
                conversation=conversa,
                message_id=message_id,
                motivo=decisao.motivo or "desconhecido",
                confianca=decisao.confianca,
            )
        else:
            conversa.agente_atual = "support"
        conversa.ultima_atividade_em = datetime.now(UTC)
        resposta = Message(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            remetente="agente",
            conteudo=decisao.texto,
            tipo="texto",
            responde_a=message_id,
            status_envio="pendente",
            timestamp=agora(),
        )
        s.add(resposta)
        await s.flush()
        return resposta.id


async def agregar_painel(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron do painel (a cada 2 min): recalcula as últimas horas de cada empresa (ADR-0008)."""
    resultado = await recalcular_todas(janela_horas=JANELA_PADRAO_HORAS)
    return {
        "empresas": resultado.empresas,
        "horas": resultado.horas,
        "falhas": len(resultado.falhas),
    }


async def agregar_painel_diario(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron diário: refaz os 2 últimos dias (correções tardias) e aplica a retenção de 400 dias."""
    resultado = await recalcular_todas(janela_horas=48, retencao_dias=RETENCAO_DIAS)
    return {
        "empresas": resultado.empresas,
        "horas": resultado.horas,
        "falhas": len(resultado.falhas),
    }


async def ingerir_remessa(ctx: dict[str, Any], remessa: str) -> dict[str, Any]:
    """Indexa os documentos enviados pelo painel (spec 004, FR-041). O resultado fica no Redis por 1 h."""
    resultado = await processar_remessa(ctx["redis"], ctx["llm"], remessa)
    return {"arquivos": len(resultado["arquivos"])}
