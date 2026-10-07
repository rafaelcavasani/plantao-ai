"""Ponto de entrada da API do Plantão.AI (FastAPI)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from redis.asyncio import Redis

from apps.api.admin import CabecalhosDeSeguranca, PainelEstatico, fechar_oidc, registrar_erros
from apps.api.admin import router as admin_router
from apps.api.routes.health import router as health_router
from apps.api.webhooks.whatsapp import router as whatsapp_webhook_router
from core.config import settings
from core.observability.logging import configurar_observabilidade
from db.painel import fechar_painel_engine
from db.session import fechar_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configurar_observabilidade()
    settings.exigir_segredos()
    app.state.queue = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    app.state.redis = Redis.from_url(settings.redis_url)
    try:
        yield
    finally:
        await app.state.queue.aclose()
        await app.state.redis.aclose()
        await fechar_engine()
        await fechar_painel_engine()
        await fechar_oidc()


app = FastAPI(
    title="Plantão.AI API",
    description="Núcleo multi-tenant de agentes de IA para automação de PMEs.",
    version="0.2.0",
    lifespan=lifespan,
)

WEB_DO_PAINEL = Path(__file__).resolve().parent.parent / "dashboard" / "web"

registrar_erros(app)
app.add_middleware(CabecalhosDeSeguranca)
app.include_router(health_router)
app.include_router(whatsapp_webhook_router)
app.include_router(admin_router)
if WEB_DO_PAINEL.is_dir():
    app.mount("/painel", PainelEstatico(directory=WEB_DO_PAINEL, html=True), name="painel")
