"""Semeia o banco de teste (`plantao_test`) com 3 empresas para as verificações do front. Rode da raiz do repositório."""

import asyncio
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, ".")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

import tests.conftest as c  # noqa: E402  (define as variáveis de ambiente de teste antes de importar a aplicação)
from core.painel.agregacao import inicio_da_hora, recalcular_todas  # noqa: E402
from tests.integration.test_painel_agregacao import popular_a, popular_b  # noqa: E402


async def main() -> None:
    engine = create_async_engine(c._ADMIN_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE readiness_checks, audit_log, channel_credentials, channel_connections, handoff_log, "
                "llm_calls, messages, conversations, leads, appointments, billing_events, usage_metrics, "
                "tenant_knowledge, knowledge_documents, painel_agregado_hora, painel_situacao, tenant_config, "
                "tenants CASCADE"
            )
        )
    a = await c.criar_tenant(engine, "Clínica Sorriso Vivo", slug="sorriso-vivo")
    b = await c.criar_tenant(engine, "Studio Fit Academia", slug="studio-fit")
    n = await c.criar_tenant(
        engine, "Ótica Visão Nova", slug="otica-visao-nova", status="em_configuracao"
    )
    await c.criar_conexao(engine, a, "sorriso-wa")
    base = inicio_da_hora(datetime.now(UTC)) - timedelta(hours=3)
    await popular_a(engine, a, base)
    await popular_b(engine, b, base)
    resultado = await recalcular_todas(agora=datetime.now(UTC))
    print("empresas agregadas:", resultado.empresas, "falhas:", resultado.falhas, a, b, n)
    await engine.dispose()


asyncio.run(main())
