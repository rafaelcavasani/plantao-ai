"""Prontidão e ativação (T041; FR-014, FR-015, SC-010)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from core.ports.channel import EstadoConexao
from core.rag.ingest import ingerir_documento
from core.tenancy import TransicaoInvalida, aplicar_alteracoes
from core.tenancy.onboarding import carregar_arquivo, criar_ou_continuar
from core.tenancy.prontidao import (
    ITEM_CONEXAO,
    ITEM_CONFIG,
    ITEM_DOCUMENTOS,
    ITEM_TESTE,
    ativar,
    avaliar_prontidao,
    registrar_teste,
)
from db.admin import admin_session
from tests.fakes.channel import FakeChannel
from tests.fakes.llm import FakeLLMClient
from tests.fakes.onboarding import escrever_empresa
from tests.fakes.pipeline import consultar


async def _preparar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    configuracao: dict[str, object] | None = None,
    documentos: dict[str, str] | None = ...,  # type: ignore[assignment]
    testar: bool = True,
) -> uuid.UUID:
    """Cria a empresa pelo onboarding e, se pedido, registra uma conversa de teste aprovada."""
    extras = {} if documentos is ... else {"documentos": documentos}
    arquivo = escrever_empresa(tmp_path, monkeypatch, configuracao=configuracao, **extras)  # type: ignore[arg-type]
    resultado = await criar_ou_continuar(
        carregar_arquivo(arquivo),
        operador="rafael",
        llm=FakeLLMClient(),
        sessao_admin=admin_session,
    )
    if testar:
        async with admin_session() as s:
            await registrar_teste(s, resultado.tenant_id, "rafael", True, {"acao": "responder"})
    return resultado.tenant_id


async def _avaliar(tenant_id: uuid.UUID, canal: FakeChannel | None = None):  # type: ignore[no-untyped-def]
    async with admin_session() as s:
        return await avaliar_prontidao(s, tenant_id, canal or FakeChannel(), "rafael")


async def test_empresa_completa_esta_pronta_e_a_ativacao_audita(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = await _preparar(tmp_path, monkeypatch)

    async with admin_session() as s:
        prontidao = await ativar(s, tenant_id, FakeChannel(), "maria")

    assert prontidao.aprovada and prontidao.pendencias == []
    empresa = (await consultar(db, "SELECT status, ativado_em FROM tenants"))[0]
    assert empresa.status == "ativo" and empresa.ativado_em is not None
    linha = (
        await consultar(
            db,
            "SELECT campo, valor_anterior, valor_novo, operador FROM audit_log "
            "WHERE entidade = 'estado'",
        )
    )[0]
    assert (linha.valor_anterior, linha.valor_novo, linha.operador) == (
        "em_configuracao",
        "ativo",
        "maria",
    )


_PENDENCIAS: dict[str, tuple[str, Callable[..., Awaitable[uuid.UUID]], FakeChannel]] = {
    "configuracao": (
        ITEM_CONFIG,
        lambda t, m: _preparar(t, m, configuracao={}),
        FakeChannel(),
    ),
    "documentos": (
        ITEM_DOCUMENTOS,
        lambda t, m: _preparar(t, m, documentos=None),
        FakeChannel(),
    ),
    "conexao": (
        ITEM_CONEXAO,
        lambda t, m: _preparar(t, m),
        FakeChannel(estado_padrao=EstadoConexao.DESCONECTADA),
    ),
    "teste": (ITEM_TESTE, lambda t, m: _preparar(t, m, testar=False), FakeChannel()),
}


@pytest.mark.parametrize("pendente", list(_PENDENCIAS))
async def test_cada_pendencia_isolada_recusa_a_ativacao_e_aparece_na_lista(
    pendente: str, db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nome_item, preparar, canal = _PENDENCIAS[pendente]
    tenant_id = await preparar(tmp_path, monkeypatch)

    async with admin_session() as s:
        prontidao = await ativar(s, tenant_id, canal, "maria")

    assert not prontidao.aprovada
    assert [i.nome for i in prontidao.pendencias] == [nome_item]
    assert (await consultar(db, "SELECT status FROM tenants"))[0].status == "em_configuracao"
    assert await consultar(db, "SELECT 1 FROM audit_log WHERE entidade = 'estado'") == []


async def test_alterar_a_configuracao_depois_do_teste_invalida_o_item_4(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = await _preparar(tmp_path, monkeypatch)
    assert (await _avaliar(tenant_id)).aprovada

    async with admin_session() as s:
        await aplicar_alteracoes(s, tenant_id, {"min_similarity": 0.5}, "maria")

    prontidao = await _avaliar(tenant_id)
    assert [i.nome for i in prontidao.pendencias] == [ITEM_TESTE]


async def test_atualizar_um_documento_depois_do_teste_invalida_o_item_4(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = await _preparar(tmp_path, monkeypatch)
    assert (await _avaliar(tenant_id)).aprovada

    resultado = await ingerir_documento(
        FakeLLMClient(), tenant_id=tenant_id, nome_origem="faq.md", conteudo=b"Mudou tudo."
    )

    assert resultado.status == "ok"
    assert [i.nome for i in (await _avaliar(tenant_id)).pendencias] == [ITEM_TESTE]


async def test_novo_teste_aprovado_revalida(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = await _preparar(tmp_path, monkeypatch)
    async with admin_session() as s:
        await aplicar_alteracoes(s, tenant_id, {"min_similarity": 0.5}, "maria")
        # o teste anterior ficou velho; um novo, depois da mudança, vale
    async with admin_session() as s:
        await registrar_teste(s, tenant_id, "maria", True)
    assert (await _avaliar(tenant_id)).aprovada


async def test_teste_reprovado_mais_recente_bloqueia(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = await _preparar(tmp_path, monkeypatch)
    async with admin_session() as s:
        await registrar_teste(s, tenant_id, "maria", False, {"acao": "handoff"})
    assert [i.nome for i in (await _avaliar(tenant_id)).pendencias] == [ITEM_TESTE]


async def test_verificar_grava_verificada_em_e_usa_a_instancia_da_empresa(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = await _preparar(tmp_path, monkeypatch)
    assert (await consultar(db, "SELECT verificada_em FROM channel_connections"))[
        0
    ].verificada_em is None
    canal = FakeChannel()

    await _avaliar(tenant_id, canal)

    assert canal.verificadas == ["clinica-nova"]
    assert (await consultar(db, "SELECT verificada_em FROM channel_connections"))[
        0
    ].verificada_em is not None


async def test_instancia_desconectada_nao_marca_como_verificada(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = await _preparar(tmp_path, monkeypatch)
    prontidao = await _avaliar(tenant_id, FakeChannel(estado_padrao=EstadoConexao.DESCONECTADA))
    item = next(i for i in prontidao.itens if i.nome == ITEM_CONEXAO)
    assert not item.ok and "desconectada" in item.detalhe
    assert (await consultar(db, "SELECT verificada_em FROM channel_connections"))[
        0
    ].verificada_em is None


async def test_cada_avaliacao_registra_um_readiness_check(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = await _preparar(tmp_path, monkeypatch, testar=False)
    await _avaliar(tenant_id)
    linha = (await consultar(db, "SELECT * FROM readiness_checks WHERE tipo = 'prontidao'"))[0]
    assert (linha.config_ok, linha.documentos_ok, linha.conexao_ok, linha.conversa_teste_ok) == (
        True,
        True,
        True,
        False,
    )
    assert linha.aprovado is False and linha.operador == "rafael"


async def test_ativar_empresa_ja_ativa_e_transicao_invalida(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = await _preparar(tmp_path, monkeypatch)
    async with admin_session() as s:
        await ativar(s, tenant_id, FakeChannel(), "maria")
    with pytest.raises(TransicaoInvalida):
        async with admin_session() as s:
            await ativar(s, tenant_id, FakeChannel(), "maria")
