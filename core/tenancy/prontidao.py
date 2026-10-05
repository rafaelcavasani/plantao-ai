"""Prontidão para ativar uma empresa e conversa de teste (FR-014, FR-015, SC-010; research R-10).

Quatro itens, reavaliados a cada pedido: configuração completa e válida, ao menos um documento indexado,
conexão verificada no provedor e conversa de teste aprovada **depois** da última mudança de configuração
ou de documento. A ativação recusa e lista o que falta; nunca ativa com pendência.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.guardrails.base import normalizar
from core.ports.channel import ChannelError, EstadoConexao, MessageChannel
from core.tenancy.ciclo_vida import Estado, mudar_estado, validar_transicao
from core.tenancy.config import ConfigEmpresa, valores_da_config
from core.tenancy.resolucao import ConexaoAusente, carregar_conexao_canal
from db.models import (
    AuditLog,
    ChannelConnection,
    KnowledgeDocument,
    ReadinessCheck,
    Tenant,
    TenantConfig,
)

ITEM_CONFIG = "configuracao completa"
ITEM_DOCUMENTOS = "documentos indexados"
ITEM_CONEXAO = "conexao verificada"
ITEM_TESTE = "conversa de teste"


@dataclass(frozen=True)
class ItemProntidao:
    nome: str
    ok: bool
    detalhe: str = ""


@dataclass(frozen=True)
class Prontidao:
    itens: tuple[ItemProntidao, ...]

    @property
    def aprovada(self) -> bool:
        return all(i.ok for i in self.itens)

    @property
    def pendencias(self) -> list[ItemProntidao]:
        return [i for i in self.itens if not i.ok]


def config_completa(config: ConfigEmpresa) -> bool:
    """Completa = tom de voz e horário de funcionamento preenchidos (o resto tem padrão válido)."""
    return bool(config.tom_de_voz.strip()) and bool(config.horario_funcionamento)


def conversa_teste_valida(
    aprovado: bool,
    executado_em: datetime | None,
    ultima_config_em: datetime | None,
    ultimo_documento_em: datetime | None,
) -> bool:
    """O teste só vale se aprovado e mais novo que a última mudança de configuração e de documento."""
    if not aprovado or executado_em is None:
        return False
    return all(
        marco is None or executado_em > marco for marco in (ultima_config_em, ultimo_documento_em)
    )


def avaliar_resposta_teste(acao: str, texto: str, esperado: Sequence[str]) -> bool:
    """Aprova ação `responder` que contém todos os termos esperados (comparação normalizada).

    Sem termos, qualquer `responder` aprova. Handoff reprova.
    """
    if acao != "responder":
        return False
    resposta = normalizar(texto)
    return all(normalizar(termo) in resposta for termo in esperado)


async def _item_config(session: AsyncSession, tenant_id: uuid.UUID) -> ItemProntidao:
    linha = await session.get(TenantConfig, tenant_id)
    if linha is None:
        return ItemProntidao(ITEM_CONFIG, False, "empresa sem configuracao")
    try:
        config = ConfigEmpresa(**valores_da_config(linha))
    except ValidationError:
        return ItemProntidao(ITEM_CONFIG, False, "configuracao com valor invalido")
    if not config_completa(config):
        faltam = [
            nome
            for nome, vazio in (
                ("tom_de_voz", not config.tom_de_voz.strip()),
                ("horario_funcionamento", not config.horario_funcionamento),
            )
            if vazio
        ]
        return ItemProntidao(ITEM_CONFIG, False, "falta preencher: " + ", ".join(faltam))
    return ItemProntidao(ITEM_CONFIG, True)


async def _item_documentos(session: AsyncSession, tenant_id: uuid.UUID) -> ItemProntidao:
    docs, trechos = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(KnowledgeDocument.num_trechos), 0)).where(
                KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.num_trechos > 0
            )
        )
    ).one()
    if not docs:
        return ItemProntidao(ITEM_DOCUMENTOS, False, "nenhum documento indexado")
    return ItemProntidao(ITEM_DOCUMENTOS, True, f"{docs} documentos, {trechos} trechos")


async def _item_conexao(
    session: AsyncSession, tenant_id: uuid.UUID, channel: MessageChannel
) -> ItemProntidao:
    try:
        conexao = await carregar_conexao_canal(session, tenant_id, "whatsapp")
    except ConexaoAusente:
        return ItemProntidao(ITEM_CONEXAO, False, "nenhuma conexao cadastrada")
    try:
        estado = await channel.verificar(conexao)
    except ChannelError as exc:
        return ItemProntidao(ITEM_CONEXAO, False, f"falha ao consultar o canal ({exc})")
    if estado is not EstadoConexao.CONECTADA:
        return ItemProntidao(
            ITEM_CONEXAO, False, f"instancia desconectada (estado: {estado.value})"
        )
    registro = (
        await session.execute(
            select(ChannelConnection).where(
                ChannelConnection.tenant_id == tenant_id, ChannelConnection.canal == "whatsapp"
            )
        )
    ).scalar_one()
    registro.verificada_em = datetime.now(UTC)
    await session.flush()
    return ItemProntidao(ITEM_CONEXAO, True, f"instancia: {conexao.instance_name}")


async def _item_teste(session: AsyncSession, tenant_id: uuid.UUID) -> ItemProntidao:
    ultimo = (
        await session.execute(
            select(ReadinessCheck)
            .where(ReadinessCheck.tenant_id == tenant_id, ReadinessCheck.tipo == "conversa_teste")
            .order_by(ReadinessCheck.executado_em.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    ultima_config = (
        await session.execute(
            select(func.max(AuditLog.criado_em)).where(
                AuditLog.tenant_id == tenant_id, AuditLog.entidade == "config"
            )
        )
    ).scalar_one()
    ultimo_documento = (
        await session.execute(
            select(func.max(KnowledgeDocument.atualizado_em)).where(
                KnowledgeDocument.tenant_id == tenant_id
            )
        )
    ).scalar_one()
    valida = ultimo is not None and conversa_teste_valida(
        bool(ultimo.aprovado), ultimo.executado_em, ultima_config, ultimo_documento
    )
    if valida:
        return ItemProntidao(ITEM_TESTE, True)
    return ItemProntidao(ITEM_TESTE, False, "nenhum teste aprovado depois da ultima alteracao")


async def avaliar_prontidao(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    channel: MessageChannel,
    operador: str,
    *,
    gravar: bool = True,
) -> Prontidao:
    """Avalia os 4 itens (a verificação do canal grava `verificada_em`) e registra o resultado.

    `session` é administrativa e a transação é do chamador (sem commit).
    """
    itens = (
        await _item_config(session, tenant_id),
        await _item_documentos(session, tenant_id),
        await _item_conexao(session, tenant_id, channel),
        await _item_teste(session, tenant_id),
    )
    resultado = Prontidao(itens)
    if gravar:
        session.add(
            ReadinessCheck(
                tenant_id=tenant_id,
                operador=operador,
                tipo="prontidao",
                config_ok=itens[0].ok,
                documentos_ok=itens[1].ok,
                conexao_ok=itens[2].ok,
                conversa_teste_ok=itens[3].ok,
                aprovado=resultado.aprovada,
                detalhes={i.nome: i.detalhe for i in itens},
            )
        )
        await session.flush()
    return resultado


async def registrar_teste(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    operador: str,
    aprovado: bool,
    detalhes: dict[str, object] | None = None,
) -> None:
    """Grava o resultado da conversa de teste. `detalhes` não pode conter texto de cliente final."""
    session.add(
        ReadinessCheck(
            tenant_id=tenant_id,
            operador=operador,
            tipo="conversa_teste",
            conversa_teste_ok=aprovado,
            aprovado=aprovado,
            detalhes=detalhes or {},
        )
    )
    await session.flush()


async def ativar(
    session: AsyncSession, tenant_id: uuid.UUID, channel: MessageChannel, operador: str
) -> Prontidao:
    """Reavalia a prontidão e ativa só se aprovada. Devolve a prontidão; `aprovada` diz se ativou.

    `TransicaoInvalida` se o estado atual não permite ativar. Com pendência, o estado não muda.
    """
    empresa = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
    validar_transicao(empresa.status, Estado.ATIVO)
    prontidao = await avaliar_prontidao(session, tenant_id, channel, operador)
    if prontidao.aprovada:
        await mudar_estado(session, tenant_id, Estado.ATIVO, operador)
    return prontidao
