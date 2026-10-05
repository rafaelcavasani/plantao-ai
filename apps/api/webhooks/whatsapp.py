"""Webhook de recebimento de mensagens do WhatsApp (contrato: specs/002-multitenancy/contracts/whatsapp-webhook.md).

A empresa é identificada pela conexão do canal (campo `instance` do corpo) e autenticada com o segredo
daquela conexão. Só autentica, valida, persiste e enfileira. Nunca chama LLM e nunca registra payload,
telefone, token nem chave de envio.
"""

from __future__ import annotations

import hmac
import logging
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from apps.api.deps import get_queue, get_redis
from apps.api.ratelimit import excedeu_limite
from core.config import settings
from core.observability.logging import definir_contexto
from core.security.crypto import get_cripto
from core.tenancy import Estado
from core.tenancy.resolucao import autenticar_entrega, resolver_conexao
from db.repositories import (
    carregar_config,
    carregar_estado_empresa,
    inserir_mensagem_lead,
    obter_ou_criar_conversa,
)
from db.session import tenant_session
from integrations.whatsapp.client import instancia_do_payload, parse_inbound

logger = logging.getLogger("plantao.webhooks.whatsapp")
router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])

_NAO_AUTORIZADO = {"detail": "invalid token"}
_FORA_DO_ALFABETO = re.compile(r"[^A-Za-z0-9._-]")


@router.get("")
async def verify_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
) -> Response:
    """Verificação de webhook exigida pela Meta Cloud API (não usada pela Evolution API)."""
    if hub_mode == "subscribe" and hmac.compare_digest(
        hub_verify_token, settings.whatsapp_verify_token
    ):
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(status_code=status.HTTP_403_FORBIDDEN)


def _instancia_para_log(instance: str) -> str:
    """Valor controlado por quem chama: só caracteres seguros e no máximo 64."""
    return _FORA_DO_ALFABETO.sub("?", instance)[:64]


@router.post("")
async def receive_message(
    request: Request,
    queue: Annotated[Any, Depends(get_queue)],
    redis: Annotated[Redis, Depends(get_redis)],
    x_webhook_token: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    try:
        payload = await request.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="corpo deve ser um objeto JSON")

    # 1. Quem é a empresa e se a entrega é dela. Instância desconhecida e token errado são
    #    indistinguíveis para quem chama (mesmo status e mesmo corpo).
    instance = instancia_do_payload(payload)
    conexao = await resolver_conexao(instance)
    if not await autenticar_entrega(conexao, x_webhook_token):
        if conexao is None:
            logger.warning(
                "conexao_desconhecida", extra={"dados": {"instance": _instancia_para_log(instance)}}
            )
        else:
            definir_contexto(tenant_id=conexao.tenant_id)
            logger.warning("token_invalido")
        return JSONResponse(_NAO_AUTORIZADO, status_code=status.HTTP_401_UNAUTHORIZED)
    assert conexao is not None
    tenant_id = conexao.tenant_id
    correlation_id = uuid.uuid4().hex
    definir_contexto(correlation_id=correlation_id, tenant_id=tenant_id)

    # 2. Só agora o corpo é interpretado: entrega não autenticada nunca chega ao parse.
    entrada = parse_inbound(payload)
    if entrada is None:
        return JSONResponse({"status": "ignored"})

    # 3. Estado e limite da empresa, lidos do banco a cada mensagem (sem cache).
    async with tenant_session(tenant_id) as session:
        estado = await carregar_estado_empresa(session)
        config = await carregar_config(session, tenant_id)
    if estado not in (Estado.ATIVO, Estado.SUSPENSO):
        logger.info("empresa_nao_ativa", extra={"dados": {"status": estado}})
        return JSONResponse({"status": "ignored"})
    suspensa = estado == Estado.SUSPENSO

    if await excedeu_limite(redis, tenant_id, config.limite_mensagens_por_minuto):
        logger.warning("rate_limited")
        return JSONResponse({"status": "rate_limited"})

    # 4. Persistir. Suspensa: guarda a mensagem com a marca e não enfileira (FR-017).
    cripto = get_cripto()
    async with tenant_session(tenant_id) as session:
        conversa = await obter_ou_criar_conversa(
            session,
            tenant_id=tenant_id,
            canal="whatsapp",
            contato_hash=cripto.hash_contato(entrada.contato),
            contato_enc=cripto.encrypt(entrada.contato),
            janela_horas=settings.conversation_reuse_hours,
            recebida_em_suspensao=suspensa,
        )
        message_id = await inserir_mensagem_lead(
            session,
            tenant_id=tenant_id,
            conversation_id=conversa.id,
            external_id=entrada.external_id,
            conteudo=entrada.conteudo,
            tipo=entrada.tipo,
        )
    if message_id is None:
        return JSONResponse({"status": "duplicate"})
    if suspensa:
        logger.info("mensagem_guardada_em_suspensao")
        return JSONResponse({"status": "suspended"})

    await queue.enqueue_job(
        "processar_mensagem",
        str(tenant_id),
        str(message_id),
        correlation_id,
        _job_id=f"{tenant_id}:{message_id}",
    )
    logger.info("mensagem_enfileirada")
    return JSONResponse({"status": "queued"})
