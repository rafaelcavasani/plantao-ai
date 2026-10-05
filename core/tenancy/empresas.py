"""Consulta de empresas por `slug` (a chave que o operador usa; FR-021)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Tenant


class EmpresaNaoEncontrada(LookupError):
    """Nenhuma empresa com o `slug` informado."""


async def obter_por_slug(session: AsyncSession, slug: str) -> Tenant:
    """Empresa pelo `slug`. `session` é administrativa (a leitura atravessa empresas)."""
    empresa = (
        await session.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if empresa is None:
        raise EmpresaNaoEncontrada(f"Empresa '{slug}' nao encontrada.")
    return empresa


async def listar(session: AsyncSession) -> list[Tenant]:
    """Todas as empresas, por `slug`."""
    return list((await session.execute(select(Tenant).order_by(Tenant.slug))).scalars())
