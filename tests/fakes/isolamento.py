"""Matriz de isolamento entre empresas (spec 002, US3: FR-028, SC-003).

Usada por três testes:
- `test_isolamento_tenants.py` roda a matriz sobre o banco real, uma entidade por caso;
- `test_isolamento_cobertura.py` confere que toda tabela com `tenant_id` está em `ENTIDADES_COBERTAS`;
- `test_isolamento_quebra.py` quebra o isolamento numa transação revertida e exige que a matriz falhe.

A matriz recebe um `AbrirSessao`: função que abre uma sessão como o papel da aplicação, com ou sem
`app.tenant_id`. Assim ela roda tanto com sessões reais (`sessao_real`) quanto dentro de uma única transação
(`sessao_na_transacao`), o que é necessário para quebrar uma política sem afetar as demais conexões.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from db.models import (
    Appointment,
    AuditLog,
    BillingEvent,
    ChannelConnection,
    ChannelCredential,
    Conversation,
    HandoffLog,
    KnowledgeDocument,
    Lead,
    LLMCall,
    Message,
    PainelAgregadoHora,
    PainelSituacao,
    ReadinessCheck,
    Tenant,
    TenantConfig,
    TenantKnowledge,
    UsageMetric,
)
from db.session import get_session_factory, tenant_session
from tests.conftest import criar_conexao

AbrirSessao = Callable[[uuid.UUID | None], AbstractAsyncContextManager[AsyncSession]]
PAPEL_APP = "plantao_app"


@dataclass
class Dados:
    """Ids das linhas criadas para uma empresa (servem para fabricar linhas válidas de escrita cruzada)."""

    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    lead_id: uuid.UUID
    documento_id: uuid.UUID
    conexao_extra_id: uuid.UUID
    linhas: dict[str, int] = field(default_factory=dict)  # tabela -> quantas linhas a empresa tem


@dataclass(frozen=True)
class Entidade:
    """Uma tabela com `tenant_id`.

    `leitura_aberta`: o diretório de roteamento (`channel_connections`) é legível por todos (exceção declarada
    ao princípio III; sem colunas sensíveis). `fabricar`: linha nova e válida da empresa `tenant_id`; `None`
    quando a chave primária é o próprio `tenant_id` (a escrita cruzada é provada pelo UPDATE).
    """

    modelo: Any
    fabricar: Callable[[uuid.UUID, Dados], Any] | None
    leitura_aberta: bool = False


def _unico() -> str:
    return uuid.uuid4().hex[:12]


ENTIDADES_COBERTAS: dict[str, Entidade] = {
    "tenant_config": Entidade(TenantConfig, None),
    "knowledge_documents": Entidade(
        KnowledgeDocument,
        lambda t, d: KnowledgeDocument(
            tenant_id=t, nome_origem=f"novo-{_unico()}.md", content_hash="h", num_trechos=0
        ),
    ),
    "tenant_knowledge": Entidade(
        TenantKnowledge,
        lambda t, d: TenantKnowledge(
            tenant_id=t,
            documento_id=d.documento_id,
            documento_origem="faq.md",
            chunk_texto="novo",
            embedding=[0.1] * 1536,
        ),
    ),
    "conversations": Entidade(
        Conversation,
        lambda t, d: Conversation(
            tenant_id=t, canal="whatsapp", contato_hash=_unico(), contato_enc="e"
        ),
    ),
    "messages": Entidade(
        Message,
        lambda t, d: Message(
            tenant_id=t,
            conversation_id=d.conversation_id,
            remetente="lead",
            conteudo="novo",
            external_id=_unico(),
        ),
    ),
    "leads": Entidade(
        Lead,
        lambda t, d: Lead(tenant_id=t, conversation_id=d.conversation_id, telefone="0"),
    ),
    "appointments": Entidade(
        Appointment,
        lambda t, d: Appointment(tenant_id=t, lead_id=d.lead_id, data_hora=datetime.now(UTC)),
    ),
    "billing_events": Entidade(
        BillingEvent, lambda t, d: BillingEvent(tenant_id=t, tipo="cobranca")
    ),
    "usage_metrics": Entidade(UsageMetric, lambda t, d: UsageMetric(tenant_id=t)),
    "handoff_log": Entidade(
        HandoffLog,
        lambda t, d: HandoffLog(tenant_id=t, conversation_id=d.conversation_id, motivo="novo"),
    ),
    "llm_calls": Entidade(
        LLMCall, lambda t, d: LLMCall(tenant_id=t, finalidade="roteador", modelo="m")
    ),
    "channel_connections": Entidade(
        ChannelConnection,
        lambda t, d: ChannelConnection(
            tenant_id=t,
            canal=f"c{_unico()}",
            provedor="evolution",
            instance_name=f"novo-{_unico()}",
        ),
        leitura_aberta=True,
    ),
    "channel_credentials": Entidade(
        ChannelCredential,
        lambda t, d: ChannelCredential(
            connection_id=d.conexao_extra_id,
            tenant_id=t,
            webhook_secret_hash="h",
            api_key_enc="k",
        ),
    ),
    "readiness_checks": Entidade(
        ReadinessCheck,
        lambda t, d: ReadinessCheck(tenant_id=t, operador="op", tipo="prontidao"),
    ),
    "painel_agregado_hora": Entidade(
        PainelAgregadoHora,
        lambda t, d: PainelAgregadoHora(
            tenant_id=t,
            hora=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(hours=int(_unico(), 16) % 100000),
        ),
    ),
    "painel_situacao": Entidade(PainelSituacao, None),
    "audit_log": Entidade(
        AuditLog,
        lambda t, d: AuditLog(tenant_id=t, entidade="config", campo="x", operador="op"),
    ),
}


async def popular(engine: AsyncEngine, tenant_id: uuid.UUID) -> Dados:
    """Cria, como admin, ao menos uma linha da empresa em cada entidade coberta."""
    async with AsyncSession(engine, expire_on_commit=False) as s:
        conversa = Conversation(
            tenant_id=tenant_id, canal="whatsapp", contato_hash="h", contato_enc="e"
        )
        doc = KnowledgeDocument(
            tenant_id=tenant_id, nome_origem="faq.md", content_hash="c", num_trechos=1
        )
        s.add_all([conversa, doc])
        await s.flush()
        mensagem = Message(
            tenant_id=tenant_id,
            conversation_id=conversa.id,
            remetente="lead",
            conteudo="oi",
            external_id="x1",
        )
        lead = Lead(tenant_id=tenant_id, conversation_id=conversa.id, telefone="1")
        extra = ChannelConnection(
            tenant_id=tenant_id,
            canal="web",
            provedor="evolution",
            instance_name=f"extra-{_unico()}",
        )
        s.add_all([mensagem, lead, extra])
        await s.flush()
        s.add_all(
            [
                TenantKnowledge(
                    tenant_id=tenant_id,
                    documento_id=doc.id,
                    documento_origem="faq.md",
                    chunk_texto="t",
                    embedding=[0.1] * 1536,
                ),
                Appointment(tenant_id=tenant_id, lead_id=lead.id, data_hora=datetime.now(UTC)),
                BillingEvent(tenant_id=tenant_id, tipo="cobranca"),
                UsageMetric(tenant_id=tenant_id),
                HandoffLog(
                    tenant_id=tenant_id,
                    conversation_id=conversa.id,
                    message_id=mensagem.id,
                    motivo="x",
                ),
                LLMCall(tenant_id=tenant_id, finalidade="roteador", modelo="m", sucesso=True),
                ReadinessCheck(tenant_id=tenant_id, operador="op", tipo="prontidao"),
                AuditLog(tenant_id=tenant_id, entidade="config", campo="x", operador="op"),
                PainelAgregadoHora(tenant_id=tenant_id, hora=datetime(2026, 1, 1, tzinfo=UTC)),
                PainelSituacao(tenant_id=tenant_id),
            ]
        )
        await s.commit()
    await criar_conexao(engine, tenant_id)  # conexão do canal whatsapp + credencial

    dados = Dados(tenant_id, conversa.id, lead.id, doc.id, extra.id)
    async with engine.connect() as conn:
        for tabela in ENTIDADES_COBERTAS:
            total = (
                await conn.execute(
                    text(f"SELECT count(*) FROM {tabela} WHERE tenant_id = :t"), {"t": tenant_id}
                )
            ).scalar_one()
            assert total >= 1, f"popular() não criou linhas em {tabela}"
            dados.linhas[tabela] = int(total)
    return dados


@asynccontextmanager
async def sessao_real(tenant_id: uuid.UUID | None) -> AsyncIterator[AsyncSession]:
    """Sessão do papel da aplicação, como a produção abre: com `tenant_session` ou sem contexto."""
    if tenant_id is None:
        async with get_session_factory()() as s:
            yield s
    else:
        async with tenant_session(tenant_id) as s:
            yield s


def sessao_na_transacao(conn: AsyncConnection) -> AbrirSessao:
    """Sessões que compartilham UMA transação de `conn` (a chamadora a reverte no fim).

    Cada sessão vira o papel da aplicação (`SET LOCAL ROLE`) e define `app.tenant_id`, como `tenant_session`.
    Um erro dentro da sessão desfaz só o ponto de salvamento dela.
    """

    @asynccontextmanager
    async def abrir(tenant_id: uuid.UUID | None) -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as s:
            await s.execute(text(f"SET LOCAL ROLE {PAPEL_APP}"))
            await s.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(tenant_id) if tenant_id else ""},
            )
            yield s
            await s.commit()

    return abrir


async def verificar_entidade(
    abrir: AbrirSessao,
    tabela: str,
    ids: dict[str, uuid.UUID],
    dados: dict[uuid.UUID, Dados],
) -> None:
    """Leitura, escrita cruzada e ausência de contexto de uma entidade. Levanta `AssertionError` no vazamento."""
    ent = ENTIDADES_COBERTAS[tabela]
    donos = list(ids.values())
    for dono in donos:
        async with abrir(dono) as s:
            visiveis = list((await s.execute(select(ent.modelo.tenant_id))).scalars().all())
        proprias = [t for t in visiveis if t == dono]
        assert len(proprias) == dados[dono].linhas[tabela], (
            f"{tabela}: a empresa não enxerga as próprias linhas ({len(proprias)})"
        )
        if ent.leitura_aberta:
            assert set(visiveis) == set(donos), f"{tabela}: leitura aberta fora do esperado"
        else:
            assert all(t == dono for t in visiveis), (
                f"{tabela}: {dono} enxerga linhas de outra empresa"
            )

        for alvo in (d for d in donos if d != dono):
            await _verificar_escrita_cruzada(abrir, tabela, ent, dono, alvo, dados[alvo])

    async with abrir(None) as s:
        sem_contexto = (await s.execute(select(ent.modelo.tenant_id))).scalars().all()
    esperado = sum(d.linhas[tabela] for d in dados.values()) if ent.leitura_aberta else 0
    assert len(sem_contexto) == esperado, (
        f"{tabela}: sem contexto devolveu {len(sem_contexto)} linhas"
    )


async def _verificar_escrita_cruzada(
    abrir: AbrirSessao,
    tabela: str,
    ent: Entidade,
    dono: uuid.UUID,
    alvo: uuid.UUID,
    dados_alvo: Dados,
) -> None:
    # UPDATE da linha de outra empresa: o RLS esconde a linha (0 afetadas) ou o papel não tem o privilégio.
    try:
        async with abrir(dono) as s:
            resultado = cast(
                "CursorResult[Any]",
                await s.execute(
                    text(f"UPDATE {tabela} SET tenant_id = tenant_id WHERE tenant_id = :y"),
                    {"y": alvo},
                ),
            )
            afetadas = resultado.rowcount
    except DBAPIError:
        afetadas = 0
    assert afetadas == 0, f"{tabela}: {dono} alterou {afetadas} linha(s) de {alvo}"

    # INSERT em nome de outra empresa: o WITH CHECK da política precisa recusar.
    if ent.fabricar is None:
        return
    try:
        async with abrir(dono) as s:
            s.add(ent.fabricar(alvo, dados_alvo))
            await s.flush()
    except DBAPIError:
        return
    raise AssertionError(f"{tabela}: {dono} gravou uma linha em nome de {alvo}")


async def verificar_busca_vetorial(
    abrir: AbrirSessao, ids: dict[str, uuid.UUID], dados: dict[uuid.UUID, Dados]
) -> None:
    for dono in ids.values():
        async with abrir(dono) as s:
            distancia = TenantKnowledge.embedding.cosine_distance([0.1] * 1536)
            achados = (
                (await s.execute(select(TenantKnowledge.tenant_id).order_by(distancia).limit(50)))
                .scalars()
                .all()
            )
        assert len(achados) == dados[dono].linhas["tenant_knowledge"]
        assert all(t == dono for t in achados), f"busca vetorial de {dono} trouxe trecho alheio"


async def verificar_tenants(abrir: AbrirSessao, ids: dict[str, uuid.UUID]) -> None:
    for dono in ids.values():
        async with abrir(dono) as s:
            vistos = (await s.execute(select(Tenant.id))).scalars().all()
        assert list(vistos) == [dono], f"tenants: {dono} enxerga {vistos}"
    async with abrir(None) as s:
        assert (await s.execute(select(Tenant.id))).scalars().all() == []


async def verificar_matriz(
    abrir: AbrirSessao, ids: dict[str, uuid.UUID], dados: dict[uuid.UUID, Dados]
) -> None:
    """Roda todas as verificações. A suíte de isolamento é a prova de SC-003."""
    for tabela in ENTIDADES_COBERTAS:
        await verificar_entidade(abrir, tabela, ids, dados)
    await verificar_busca_vetorial(abrir, ids, dados)
    await verificar_tenants(abrir, ids)


async def popular_todas(engine: AsyncEngine, ids: dict[str, uuid.UUID]) -> dict[uuid.UUID, Dados]:
    return {tenant_id: await popular(engine, tenant_id) for tenant_id in ids.values()}
