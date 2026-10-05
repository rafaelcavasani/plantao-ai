"""Webhook de recebimento de mensagens do WhatsApp (contrato: contracts/whatsapp-webhook.md).

Só autentica, valida, persiste e enfileira. Nunca chama LLM e nunca registra payload ou telefone.
"""

from __future__ import annotations

import hmac
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from apps.api.deps import get_queue, get_redis, get_tenant_id
from apps.api.ratelimit import excedeu_limite
from core.config import settings
from core.observability.logging import definir_contexto
from core.security.crypto import get_cripto
from db.repositories import inserir_mensagem_lead, obter_ou_criar_conversa
from db.session import tenant_session
from integrations.whatsapp.client import parse_inbound

logger = logging.getLogger("plantao.webhooks.whatsapp")
router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])


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


def _token_valido(token: str | None) -> bool:
    segredo = settings.whatsapp_webhook_secret
    return bool(segredo) and token is not None and hmac.compare_digest(token, segredo)


@router.post("")
async def receive_message(
    request: Request,
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    queue: Annotated[Any, Depends(get_queue)],
    redis: Annotated[Redis, Depends(get_redis)],
    x_webhook_token: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    if not _token_valido(x_webhook_token):
        return JSONResponse({"detail": "invalid token"}, status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        payload = await request.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="corpo deve ser um objeto JSON")

    entrada = parse_inbound(payload)
    if entrada is None:
        return JSONResponse({"status": "ignored"})

    correlation_id = uuid.uuid4().hex
    definir_contexto(correlation_id=correlation_id, tenant_id=tenant_id)

    if await excedeu_limite(redis, tenant_id, settings.rate_limit_msgs_per_min):
        logger.warning("rate_limited")
        return JSONResponse({"status": "rate_limited"})

    cripto = get_cripto()
    async with tenant_session(tenant_id) as session:
        conversa = await obter_ou_criar_conversa(
            session,
            tenant_id=tenant_id,
            canal="whatsapp",
            contato_hash=cripto.hash_contato(entrada.contato),
            contato_enc=cripto.encrypt(entrada.contato),
            janela_horas=settings.conversation_reuse_hours,
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

    await queue.enqueue_job(
        "processar_mensagem",
        str(tenant_id),
        str(message_id),
        correlation_id,
        _job_id=str(message_id),
    )
    logger.info("mensagem_enfileirada")
    return JSONResponse({"status": "queued"})
