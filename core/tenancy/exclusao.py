"""Encerramento e exclusão de dados de uma empresa (US6; FR-019, FR-020, SC-008; research R-11, ADR 0004).

`encerrar` muda o estado para `encerrado` (bloqueia respostas; o número continua reservado).
`apagar_dados` só roda com a empresa encerrada, a confirmação pelo nome exato e a drenagem cumprida. Apaga na
ordem das chaves estrangeiras, numa transação com o papel da aplicação (a RLS impede alcançar outra empresa),
mantém a linha de `tenants` como marca e a trilha de `audit_log`, e limpa as chaves de limite no Redis.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, cast

from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.tenancy.auditoria import registrar_mudanca
from core.tenancy.ciclo_vida import Estado, mudar_estado
from core.tenancy.empresas import EmpresaNaoEncontrada
from db.models import (
    Appointment,
    BillingEvent,
    ChannelConnection,
    ChannelCredential,
    Conversation,
    HandoffLog,
    KnowledgeDocument,
    Lead,
    LLMCall,
    Message,
    ReadinessCheck,
    Tenant,
    TenantConfig,
    TenantKnowledge,
    UsageMetric,
)
from db.session import tenant_session

SessaoAdmin = Callable[[], AbstractAsyncContextManager[AsyncSession]]

# Ordem de exclusão: filhas antes das mães (chaves estrangeiras). `audit_log` e `tenants` ficam.
ORDEM_DE_EXCLUSAO: Final[tuple[tuple[str, Any], ...]] = (
    ("repasses", HandoffLog),
    ("usos", LLMCall),
    ("agendamentos", Appointment),
    ("leads", Lead),
    ("mensagens", Message),
    ("conversas", Conversation),
    ("cobrancas", BillingEvent),
    ("metricas", UsageMetric),
    ("trechos", TenantKnowledge),
    ("documentos", KnowledgeDocument),
    ("prontidoes", ReadinessCheck),
    ("credenciais", ChannelCredential),
    ("conexoes", ChannelConnection),
    ("configuracao", TenantConfig),
)


class ExclusaoRecusada(Exception):
    """A exclusão não foi feita. A mensagem explica o motivo; nada foi apagado."""


@dataclass(frozen=True)
class ResultadoExclusao:
    """O que `apagar_dados` removeu. Só números e o nome da instância (nunca dado de cliente final)."""

    contagens: dict[str, int] = field(default_factory=dict)
    instance_name: str | None = None
    chaves_redis: int = 0
    encerrada_ha_segundos: float = 0.0
    drenagem_segundos: int = 0


async def encerrar(
    session: AsyncSession, tenant_id: uuid.UUID, operador: str, *, motivo: str | None = None
) -> Estado:
    """`-> encerrado` (FR-019). O número continua reservado até a exclusão. Sem commit."""
    return await mudar_estado(session, tenant_id, Estado.ENCERRADO, operador, motivo=motivo)


async def _conferir(
    sessao_admin: SessaoAdmin,
    tenant_id: uuid.UUID,
    confirmacao: str,
    espera: int,
    agora: datetime,
) -> tuple[str, str, float]:
    """Valida as condições da exclusão. Devolve (nome, slug, segundos desde o encerramento)."""
    async with sessao_admin() as s:
        empresa = await s.get(Tenant, tenant_id)
        if empresa is None:
            raise EmpresaNaoEncontrada(f"Empresa {tenant_id} nao encontrada.")
        if empresa.dados_apagados_em is not None:
            raise ExclusaoRecusada(
                f"Os dados da empresa '{empresa.slug}' ja foram apagados "
                f"em {empresa.dados_apagados_em:%Y-%m-%dT%H:%M:%SZ}."
            )
        if empresa.status != Estado.ENCERRADO.value or empresa.encerrado_em is None:
            raise ExclusaoRecusada(
                f"A empresa precisa estar encerrada para apagar os dados (estado atual: "
                f"{empresa.status}). Rode close antes."
            )
        if confirmacao != empresa.nome_empresa:
            raise ExclusaoRecusada(
                "Confirmacao incorreta: informe o nome exato da empresa em --confirmar."
            )
        decorrido = (agora - empresa.encerrado_em).total_seconds()
        if decorrido < espera:
            raise ExclusaoRecusada(
                f"Drenagem em andamento: encerrada ha {int(decorrido)} s e o minimo e {espera} s. "
                f"Aguarde {int(espera - decorrido) + 1} s para os jobs em andamento terminarem."
            )
        return empresa.nome_empresa, empresa.slug, decorrido


async def _limpar_redis(redis: Redis, tenant_id: uuid.UUID) -> int:
    """Remove as chaves de limite `rl:{tenant}:*` da empresa. Devolve quantas foram removidas."""
    chaves = [chave async for chave in redis.scan_iter(match=f"rl:{tenant_id}:*")]
    if not chaves:
        return 0
    return int(await redis.delete(*chaves))


async def apagar_dados(
    sessao_admin: SessaoAdmin,
    tenant_id: uuid.UUID,
    confirmacao: str,
    operador: str,
    *,
    redis: Redis | None = None,
    drenagem_segundos: int | None = None,
    agora: datetime | None = None,
) -> ResultadoExclusao:
    """Apaga todos os dados da empresa encerrada, menos a marca em `tenants` e a trilha de auditoria.

    `ExclusaoRecusada` se a empresa não está encerrada, a confirmação não é o nome exato, a drenagem
    não foi cumprida ou os dados já foram apagados. Repetir depois de uma falha no meio é seguro: as
    linhas já apagadas simplesmente não existem mais.
    """
    espera = settings.purge_drenagem_segundos if drenagem_segundos is None else drenagem_segundos
    nome, slug, decorrido = await _conferir(
        sessao_admin, tenant_id, confirmacao, espera, agora or datetime.now(UTC)
    )

    contagens: dict[str, int] = {}
    async with tenant_session(tenant_id) as s:
        instancia = (
            (
                await s.execute(
                    select(ChannelConnection.instance_name).where(
                        ChannelConnection.tenant_id == tenant_id
                    )
                )
            )
            .scalars()
            .first()
        )
        for rotulo, modelo in ORDEM_DE_EXCLUSAO:
            resultado = cast(
                "CursorResult[Any]",
                await s.execute(delete(modelo).where(modelo.tenant_id == tenant_id)),
            )
            contagens[rotulo] = int(resultado.rowcount)
        await registrar_mudanca(
            s, tenant_id, "dados", "exclusao", None, {"nome_empresa": nome, "slug": slug}, operador
        )

    async with sessao_admin() as s:
        empresa = await s.get(Tenant, tenant_id)
        if empresa is not None:
            empresa.dados_apagados_em = datetime.now(UTC)

    chaves = await _limpar_redis(redis, tenant_id) if redis is not None else 0
    return ResultadoExclusao(contagens, instancia, chaves, decorrido, espera)
