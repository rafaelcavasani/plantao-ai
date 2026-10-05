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
from core.config import settings
from core.handoff.service import registrar_handoff
from core.observability.logging import definir_contexto, limpar_contexto
from core.ports.channel import ChannelError, MessageChannel
from core.security.crypto import get_cripto
from db.models import Conversation, Message
from db.repositories import (
    agora,
    carregar_config,
    carregar_historico,
    resposta_existente,
    ultima_atividade_humana,
)
from db.session import tenant_session

logger = logging.getLogger("plantao.worker")


def _handoff_expirou(handoff_em: datetime | None, ultima_humana: datetime | None) -> bool:
    """O handoff expira `handoff_ttl_minutes` após a última atividade humana (ou o próprio handoff)."""
    referencias = [d for d in (handoff_em, ultima_humana) if d is not None]
    if not referencias:
        return True
    return agora() - max(referencias) >= timedelta(minutes=settings.handoff_ttl_minutes)


async def processar_mensagem(
    ctx: dict[str, Any], tenant_id: str, message_id: str, correlation_id: str = ""
) -> str:
    """Devolve um código do resultado: `respondida`, `handoff`, `ja_respondida`, `handoff_ativo`,
    `mensagem_inexistente`. `ctx` traz `grafo` (Grafo) e `channel` (MessageChannel)."""
    limpar_contexto()
    tid, mid = uuid.UUID(tenant_id), uuid.UUID(message_id)
    definir_contexto(correlation_id=correlation_id, tenant_id=tid)
    grafo: Grafo = ctx["grafo"]
    channel: MessageChannel = ctx["channel"]

    # Fase 1: leitura -------------------------------------------------------------------------
    async with tenant_session(tid) as s:
        mensagem = await s.get(Message, mid)
        if mensagem is None:
            logger.warning("mensagem_inexistente")
            return "mensagem_inexistente"
        if await resposta_existente(s, mid) is not None:
            return "ja_respondida"
        conversa = await s.get(Conversation, mensagem.conversation_id)
        assert conversa is not None
        definir_contexto(conversation_id=conversa.id)
        if conversa.status == "handoff":
            humana = await ultima_atividade_humana(s, conversa.id)
            if not _handoff_expirou(conversa.handoff_em, humana):
                logger.info("handoff_ativo")
                return "handoff_ativo"
            conversa.status, conversa.agente_atual, conversa.handoff_em = "aberta", "router", None
        config = ConfigTenant.de_modelo(await carregar_config(s, tid))
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
    except IntegrityError:
        logger.info("ja_respondida_concorrente")
        return "ja_respondida"

    # Fase 4: envio -----------------------------------------------------------------------------
    try:
        await channel.send_text(contato, decisao.texto)
        status_envio = "enviada"
    except ChannelError as exc:
        status_envio = "falha"
        logger.error("falha_envio", extra={"dados": {"erro": str(exc)}})
    async with tenant_session(tid) as s:
        await s.execute(
            update(Message).where(Message.id == resposta_id).values(status_envio=status_envio)
        )
    return "handoff" if decisao.acao == "handoff" else "respondida"


async def _gravar(
    tenant_id: uuid.UUID, message_id: uuid.UUID, conversation_id: uuid.UUID, decisao: Decisao
) -> uuid.UUID:
    async with tenant_session(tenant_id) as s:
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
