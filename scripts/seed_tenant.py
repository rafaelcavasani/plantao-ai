"""Cria (ou reaproveita) o tenant piloto com a configuração completa e imprime o `PILOT_TENANT_ID`.

    python -m scripts.seed_tenant

Usa a conexão administrativa (`DATABASE_ADMIN_URL`), pois a criação de tenants não passa por RLS.
É idempotente: se o tenant piloto já existe, só imprime o id.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core.config import settings
from db.models import PALAVRAS_GATILHO_PADRAO, Tenant, TenantConfig

NOME_PILOTO = "Clínica Sorriso (piloto)"


async def criar_piloto(admin_url: str | None = None) -> uuid.UUID:
    engine = create_async_engine(admin_url or settings.database_admin_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            existente = (
                await session.execute(select(Tenant).where(Tenant.nome_empresa == NOME_PILOTO))
            ).scalar_one_or_none()
            if existente is not None:
                return existente.id
            tenant = Tenant(
                nome_empresa=NOME_PILOTO,
                nicho="clinica_odontologica",
                plano="recepcionista",
                status="ativo",
            )
            session.add(tenant)
            await session.flush()
            session.add(
                TenantConfig(
                    tenant_id=tenant.id,
                    tom_de_voz="Cordial, acolhedor e direto. Trate o cliente por 'você'.",
                    horario_funcionamento={"seg_sex": "08:00-18:00", "sabado": "08:00-12:00"},
                    limite_desconto_percentual=10.0,
                    topicos_proibidos=[
                        "garantia de resultado",
                        "diagnóstico",
                        "prescrição de medicamentos",
                    ],
                    confianca_minima_handoff=0.7,
                    palavras_gatilho=list(PALAVRAS_GATILHO_PADRAO),
                    router_confidence_threshold=0.6,
                    min_similarity=0.30,
                )
            )
            await session.commit()
            return tenant.id
    finally:
        await engine.dispose()


def main() -> None:
    tenant_id = asyncio.run(criar_piloto())
    print(f"Tenant piloto: {tenant_id}")
    print(f"Adicione ao .env:  PILOT_TENANT_ID={tenant_id}")


if __name__ == "__main__":
    main()
