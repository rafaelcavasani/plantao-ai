"""Configuração do worker ARQ. Execute com: `arq apps.worker.settings.WorkerSettings`."""

from __future__ import annotations

from typing import Any

from arq import cron
from arq.connections import RedisSettings

from agents.orchestrator.graph import build_graph
from apps.composition import build_channel, build_llm_client
from apps.worker.jobs import (
    agregar_painel,
    agregar_painel_diario,
    ingerir_remessa,
    processar_mensagem,
)
from core.config import settings
from core.observability.logging import configurar_observabilidade


async def on_startup(ctx: dict[str, Any]) -> None:
    configurar_observabilidade()
    settings.exigir_segredos()
    llm = build_llm_client()
    ctx["llm"] = llm
    ctx["channel"] = build_channel()
    ctx["grafo"] = build_graph(llm)


async def on_shutdown(ctx: dict[str, Any]) -> None:
    for chave in ("llm", "channel"):
        fechar = getattr(ctx.get(chave), "aclose", None)
        if fechar is not None:
            await fechar()


class WorkerSettings:
    functions = [processar_mensagem, agregar_painel, agregar_painel_diario, ingerir_remessa]
    # Painel (spec 004): números com no máximo 5 minutos de atraso; refaz os 2 últimos dias às 03:00 UTC.
    cron_jobs = [
        cron(agregar_painel, minute=set(range(0, 60, 2)), run_at_startup=True, timeout=110),
        cron(agregar_painel_diario, hour=3, minute=0, timeout=600),
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_tries = 3
    job_timeout = 120
