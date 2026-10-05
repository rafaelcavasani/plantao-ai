"""Ciclo de vida da empresa: estados, transições permitidas e mudança de estado auditada (FR-011)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.tenancy.auditoria import registrar_mudanca
from db.models import Tenant
from db.repositories import travar_estado_exclusiva


class Estado(StrEnum):
    EM_CONFIGURACAO = "em_configuracao"
    ATIVO = "ativo"
    SUSPENSO = "suspenso"
    ENCERRADO = "encerrado"


# A ordem dos destinos é a ordem exibida na mensagem de erro.
TRANSICOES: dict[Estado, tuple[Estado, ...]] = {
    Estado.EM_CONFIGURACAO: (Estado.ATIVO, Estado.ENCERRADO),
    Estado.ATIVO: (Estado.SUSPENSO, Estado.ENCERRADO),
    Estado.SUSPENSO: (Estado.ATIVO, Estado.ENCERRADO),
    Estado.ENCERRADO: (),
}


class TransicaoInvalida(ValueError):
    """Mudança de estado fora da tabela `TRANSICOES`."""


def validar_transicao(atual: Estado | str, novo: Estado | str) -> None:
    """Levanta `TransicaoInvalida` se `atual -> novo` não for permitida.

    Estado desconhecido levanta `ValueError`.
    """
    de, para = Estado(atual), Estado(novo)
    permitidos = TRANSICOES[de]
    if para not in permitidos:
        lista = ", ".join(e.value for e in permitidos) or "nenhum"
        raise TransicaoInvalida(
            f"Transicao invalida: {de.value} -> {para.value}. "
            f"Permitido a partir de {de.value}: {lista}."
        )


async def mudar_estado(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novo: Estado | str,
    operador: str,
    *,
    motivo: str | None = None,
    exigir_de: Estado | None = None,
) -> Estado:
    """Muda o estado da empresa na transação da `session` (administrativa) e audita. Sem commit.

    Pega a trava advisory exclusiva do estado: espera quem está gravando uma resposta (research R-06).
    Devolve o estado anterior. `TransicaoInvalida` se a mudança não for permitida ou se `exigir_de`
    for informado e o estado atual for outro.
    """
    await travar_estado_exclusiva(session, tenant_id)
    empresa = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    ).scalar_one()
    anterior = Estado(empresa.status)
    destino = Estado(novo)
    if exigir_de is not None and anterior is not exigir_de:
        raise TransicaoInvalida(
            f"Transicao invalida: {anterior.value} -> {destino.value}. "
            f"So vale a partir de {exigir_de.value}."
        )
    validar_transicao(anterior, destino)
    agora = datetime.now(UTC)
    empresa.status = destino.value
    if destino is Estado.ATIVO and empresa.ativado_em is None:
        empresa.ativado_em = agora
    if destino is Estado.ENCERRADO:
        empresa.encerrado_em = agora
    await registrar_mudanca(
        session, tenant_id, "estado", "status", anterior.value, destino.value, operador
    )
    if motivo:
        await registrar_mudanca(session, tenant_id, "estado", "motivo", None, motivo, operador)
    return anterior


async def suspender(
    session: AsyncSession, tenant_id: uuid.UUID, operador: str, *, motivo: str | None = None
) -> Estado:
    """`ativo -> suspenso` (FR-016). O motivo, se houver, vai para a auditoria. Sem commit."""
    return await mudar_estado(session, tenant_id, Estado.SUSPENSO, operador, motivo=motivo)


async def retomar(session: AsyncSession, tenant_id: uuid.UUID, operador: str) -> Estado:
    """`suspenso -> ativo` (FR-018). Recusa outros estados: ativar uma empresa nova exige a prontidão."""
    return await mudar_estado(session, tenant_id, Estado.ATIVO, operador, exigir_de=Estado.SUSPENSO)
