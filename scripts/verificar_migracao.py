"""Confere se o banco está na migração do painel (`0005`) antes de usar os comandos do painel."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from db.admin import admin_session, fechar_admin_engine

MENSAGEM = (
    "O banco ainda não tem as tabelas do painel (migração 0005). "
    "Rode `make migrate` e tente de novo."
)


async def migracao_em_dia() -> bool:
    async with admin_session() as s:
        achou = await s.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'tenants' AND column_name = 'versao'"
            )
        )
        return achou.first() is not None


async def exigir_migracao() -> None:
    """Encerra com instrução clara (sem traceback) se a migração do painel não foi aplicada."""
    if not await migracao_em_dia():
        await fechar_admin_engine()
        raise SystemExit(MENSAGEM)


def exigir_migracao_sincrono() -> None:
    asyncio.run(exigir_migracao())
    # `asyncio.run` fecha o loop; o engine administrativo usa NullPool, então não sobra conexão aberta.
