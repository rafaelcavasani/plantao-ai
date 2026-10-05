"""Onboarding repetível de empresas (T040; FR-012, FR-013, FR-002, FR-005)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from core.tenancy import ConexaoEmUso, aplicar_alteracoes
from core.tenancy.onboarding import ArquivoInvalido, carregar_arquivo, criar_ou_continuar
from db.admin import admin_session
from scripts.tenants import principal
from tests.conftest import criar_conexao
from tests.fakes.llm import FakeLLMClient
from tests.fakes.onboarding import CHAVE_ENVIO, SEGREDO_ENTREGA, escrever_empresa
from tests.fakes.pipeline import consultar


async def _criar(arquivo: Path, llm: FakeLLMClient | None = None, operador: str = "rafael"):  # type: ignore[no-untyped-def]
    return await criar_ou_continuar(
        carregar_arquivo(arquivo),
        operador=operador,
        llm=llm or FakeLLMClient(),
        sessao_admin=admin_session,
    )


async def _contagens(db: AsyncEngine) -> dict[str, int]:
    saida = {}
    for tabela in ("tenants", "tenant_config", "channel_connections", "channel_credentials"):
        saida[tabela] = len(await consultar(db, f"SELECT 1 FROM {tabela}"))
    saida["documentos"] = len(await consultar(db, "SELECT 1 FROM knowledge_documents"))
    saida["trechos"] = len(await consultar(db, "SELECT 1 FROM tenant_knowledge"))
    saida["auditoria"] = len(await consultar(db, "SELECT 1 FROM audit_log"))
    return saida


async def test_criacao_do_zero_deixa_a_empresa_em_configuracao_completa(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arquivo = escrever_empresa(tmp_path, monkeypatch)
    resultado = await _criar(arquivo)

    assert resultado.novo and not resultado.falhou
    empresa = (await consultar(db, "SELECT * FROM tenants"))[0]
    assert (empresa.slug, empresa.status) == ("clinica-nova", "em_configuracao")
    cfg = (await consultar(db, "SELECT * FROM tenant_config"))[0]
    assert cfg.tom_de_voz == "Cordial e direto." and cfg.horario_funcionamento["sabado"]
    assert cfg.handoff_ttl_minutos == 60 and "procon" in cfg.palavras_gatilho  # padrão aplicado
    conexao = (await consultar(db, "SELECT * FROM channel_connections"))[0]
    assert (conexao.instance_name, conexao.provedor) == ("clinica-nova", "evolution")
    assert len(await consultar(db, "SELECT 1 FROM channel_credentials")) == 1
    assert len(await consultar(db, "SELECT 1 FROM knowledge_documents")) == 2
    assert len(await consultar(db, "SELECT 1 FROM tenant_knowledge")) >= 2
    assert [p.nome for p in resultado.passos] == [
        "empresa",
        "configuracao",
        "conexao",
        "credenciais",
        "documentos",
        "resumo",
    ]


async def test_segundo_create_nao_duplica_nem_audita(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arquivo = escrever_empresa(tmp_path, monkeypatch)
    await _criar(arquivo)
    antes = await _contagens(db)

    resultado = await _criar(arquivo)

    assert not resultado.novo and not resultado.falhou
    assert await _contagens(db) == antes
    assert {d.status for d in resultado.documentos} == {"inalterado"}


async def test_interrupcao_no_passo_de_documentos_e_repeticao_conclui_o_restante(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arquivo = escrever_empresa(tmp_path, monkeypatch)

    primeira = await _criar(arquivo, FakeLLMClient(falhar_embedding=True))

    assert primeira.falhou
    assert (await consultar(db, "SELECT status FROM tenants"))[0].status == "em_configuracao"
    assert len(await consultar(db, "SELECT 1 FROM channel_connections")) == 1
    assert await consultar(db, "SELECT 1 FROM knowledge_documents") == []

    segunda = await _criar(arquivo)

    assert not segunda.falhou and not segunda.novo
    assert len(await consultar(db, "SELECT 1 FROM tenants")) == 1
    assert len(await consultar(db, "SELECT 1 FROM channel_connections")) == 1
    assert len(await consultar(db, "SELECT 1 FROM knowledge_documents")) == 2


async def test_empresa_ativa_continua_ativa_ao_repetir(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arquivo = escrever_empresa(tmp_path, monkeypatch)
    await _criar(arquivo)
    async with db.begin() as conn:
        from sqlalchemy import text

        await conn.execute(text("UPDATE tenants SET status = 'ativo'"))

    resultado = await _criar(arquivo)

    assert resultado.estado == "ativo"
    assert (await consultar(db, "SELECT status FROM tenants"))[0].status == "ativo"


async def test_instancia_de_outra_empresa_e_recusada_sem_gravar_nada(
    db: AsyncEngine, tenant_a: uuid.UUID, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await criar_conexao(db, tenant_a, instance_name="numero-compartilhado")
    antes = await _contagens(db)
    arquivo = escrever_empresa(tmp_path, monkeypatch, instance="numero-compartilhado")

    with pytest.raises(ConexaoEmUso):
        await _criar(arquivo)

    assert await _contagens(db) == antes
    assert await consultar(db, "SELECT 1 FROM tenants WHERE slug = 'clinica-nova'") == []


async def test_arquivo_invalido_nao_cria_nada(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arquivo = escrever_empresa(tmp_path, monkeypatch, slug="Slug Invalido")
    with pytest.raises(ArquivoInvalido):
        await _criar(arquivo)
    assert await _contagens(db) == dict.fromkeys(await _contagens(db), 0)


async def test_mudanca_de_campos_gera_uma_linha_de_auditoria_por_campo(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _criar(escrever_empresa(tmp_path, monkeypatch))
    base = len(await consultar(db, "SELECT 1 FROM audit_log WHERE entidade = 'config'"))

    arquivo = escrever_empresa(
        tmp_path,
        monkeypatch,
        configuracao={
            "tom_de_voz": "Formal.",
            "horario_funcionamento": {"seg_sex": "08:00-18:00", "sabado": "08:00-12:00"},
            "min_similarity": 0.5,
        },
    )
    resultado = await _criar(arquivo, operador="maria")

    linhas = await consultar(
        db,
        "SELECT campo, valor_anterior, valor_novo, operador FROM audit_log "
        "WHERE entidade = 'config' AND operador = 'maria' ORDER BY campo",
    )
    assert [(linha.campo, linha.valor_anterior, linha.valor_novo) for linha in linhas] == [
        ("min_similarity", 0.3, 0.5),
        ("tom_de_voz", "Cordial e direto.", "Formal."),
    ]
    assert len(await consultar(db, "SELECT 1 FROM audit_log WHERE entidade = 'config'")) == base + 2
    assert any("2" in p.detalhe for p in resultado.passos if p.nome == "configuracao")


async def test_campo_omitido_no_arquivo_nao_desfaz_ajuste_do_operador(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arquivo = escrever_empresa(tmp_path, monkeypatch)
    resultado = await _criar(arquivo)
    async with admin_session() as s:
        await aplicar_alteracoes(s, resultado.tenant_id, {"handoff_ttl_minutos": 30}, "maria")

    await _criar(arquivo)

    assert (await consultar(db, "SELECT handoff_ttl_minutos FROM tenant_config"))[
        0
    ].handoff_ttl_minutos == 30


async def test_credenciais_ficam_cifradas_e_fora_da_auditoria(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _criar(escrever_empresa(tmp_path, monkeypatch))
    cred = (await consultar(db, "SELECT * FROM channel_credentials"))[0]
    assert CHAVE_ENVIO not in cred.api_key_enc and SEGREDO_ENTREGA not in cred.webhook_secret_hash
    auditoria = " ".join(
        str(dict(r._mapping)) for r in await consultar(db, "SELECT * FROM audit_log")
    )
    assert CHAVE_ENVIO not in auditoria and SEGREDO_ENTREGA not in auditoria


async def test_nenhum_valor_de_credencial_em_saida_nem_logs(
    db: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    arquivo = escrever_empresa(tmp_path, monkeypatch)
    with caplog.at_level("DEBUG"):
        assert (
            await principal(
                ["create", "--file", str(arquivo), "--operador", "rafael"], FakeLLMClient()
            )
            == 0
        )
        assert (
            await principal(
                ["create", "--file", str(arquivo), "--operador", "rafael"], FakeLLMClient()
            )
            == 0
        )
    saida = capsys.readouterr()
    todo = saida.out + saida.err + caplog.text
    assert CHAVE_ENVIO not in todo and SEGREDO_ENTREGA not in todo
