"""Configuração por empresa: alteração, validação e auditoria (US5, T072; FR-008 a FR-010, FR-029, SC-005).

Banco real, canal e LLM falsos. A configuração é lida do banco a cada mensagem, então a alteração vale na próxima
mensagem sem reiniciar o worker.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from apps.worker.jobs import processar_mensagem
from core.llm.ports import Finalidade
from core.tenancy.config import ConfigInvalida, aplicar_alteracoes
from db.admin import admin_session
from db.config_padrao import CONFIG_PADRAO, nova_config_padrao
from scripts.tenants import principal
from tests.conftest import criar_conexao, criar_tenant
from tests.fakes.channel import FakeChannel
from tests.fakes.conhecimento import inserir_conhecimento, json_roteador, json_suporte
from tests.fakes.llm import FakeLLMClient
from tests.fakes.pipeline import consultar, contexto, receber, slug_de

pytestmark = pytest.mark.integration

TEXTO = "Desconto de 5% para pagamento à vista."
PERGUNTA = "Qual o desconto para pagamento à vista?"
OPERADOR = ["--operador", "rafael"]


async def _empresa(db: AsyncEngine, nome: str, instancia: str, **config: object) -> uuid.UUID:
    tenant_id = await criar_tenant(db, nome, **config)
    await criar_conexao(db, tenant_id, instance_name=instancia)
    return tenant_id


async def _llm_com_desconto(db: AsyncEngine, tenant_id: uuid.UUID, n: int = 3) -> FakeLLMClient:
    ids = await inserir_conhecimento(db, tenant_id, {"promo.md": [TEXTO]})
    trecho = str(ids["promo.md"][0])
    return FakeLLMClient(
        {
            Finalidade.ROTEADOR: [json_roteador()] * n,
            Finalidade.SUPORTE: [json_suporte("Temos desconto de 5% à vista.", 0.95, [trecho])] * n,
        }
    )


async def _alterar(tenant_id: uuid.UUID, **campos: object) -> list[str]:
    async with admin_session() as s:
        return await aplicar_alteracoes(s, tenant_id, campos, "rafael")


async def _config(db: AsyncEngine, tenant_id: uuid.UUID) -> object:
    return (await consultar(db, "SELECT * FROM tenant_config WHERE tenant_id = :t", t=tenant_id))[0]


async def _responder(
    tenant_id: uuid.UUID, llm: FakeLLMClient, canal: FakeChannel, contato: str
) -> str:
    mid, _ = await receber(tenant_id, PERGUNTA, contato=contato)
    return await processar_mensagem(contexto(llm, canal), str(tenant_id), str(mid), "corr-cfg")


# --- FR-010: vale na próxima mensagem, sem reinício ------------------------------------------------
async def test_alteracao_vale_na_proxima_mensagem_e_a_outra_empresa_nao_muda(
    db: AsyncEngine,
) -> None:
    a = await _empresa(db, "Clínica A", "inst-a", limite_desconto_percentual=0.0)
    b = await _empresa(db, "Clínica B", "inst-b", limite_desconto_percentual=0.0)
    llm_a, llm_b = await _llm_com_desconto(db, a), await _llm_com_desconto(db, b)
    canal = FakeChannel()

    assert await _responder(a, llm_a, canal, "5511911110001@s.whatsapp.net") == "handoff"

    assert await _alterar(a, limite_desconto_percentual=10.0) == ["limite_desconto_percentual"]

    assert await _responder(a, llm_a, canal, "5511911110002@s.whatsapp.net") == "respondida"
    assert await _responder(b, llm_b, canal, "5511911110003@s.whatsapp.net") == "handoff"
    assert [i for i, _, _ in canal.envios] == ["inst-a", "inst-a", "inst-b"]
    assert canal.envios[1][2] == "Temos desconto de 5% à vista."
    assert (await _config(db, b)).limite_desconto_percentual == 0.0  # type: ignore[attr-defined]


async def test_mensagem_ja_respondida_nao_e_reprocessada_depois_da_alteracao(
    db: AsyncEngine,
) -> None:
    a = await _empresa(db, "Clínica A", "inst-a", limite_desconto_percentual=10.0)
    llm = await _llm_com_desconto(db, a)
    canal = FakeChannel()
    mid, _ = await receber(a, PERGUNTA)
    ctx = contexto(llm, canal)
    assert await processar_mensagem(ctx, str(a), str(mid), "c1") == "respondida"

    await _alterar(a, limite_desconto_percentual=0.0)

    assert await processar_mensagem(ctx, str(a), str(mid), "c2") == "ja_respondida"
    assert len(canal.envios) == 1


# --- auditoria por campo (FR-029) ------------------------------------------------------------------
async def test_uma_linha_de_auditoria_por_campo_com_anterior_novo_operador_e_data(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    alterados = await _alterar(tenant_a, min_similarity=0.5, handoff_ttl_minutos=30)

    assert alterados == ["min_similarity", "handoff_ttl_minutos"]
    linhas = await consultar(
        db,
        "SELECT campo, valor_anterior, valor_novo, operador, criado_em FROM audit_log "
        "WHERE entidade = 'config' AND tenant_id = :t ORDER BY campo",
        t=tenant_a,
    )
    assert [(r.campo, r.valor_anterior, r.valor_novo, r.operador) for r in linhas] == [
        ("handoff_ttl_minutos", 60, 30, "rafael"),
        ("min_similarity", 0.3, 0.5, "rafael"),
    ]
    assert all(r.criado_em is not None for r in linhas)


async def test_comando_audit_lista_as_linhas_da_empresa(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID, capsys: pytest.CaptureFixture[str]
) -> None:
    await _alterar(tenant_a, min_similarity=0.5)
    await _alterar(tenant_b, min_similarity=0.9)
    capsys.readouterr()

    assert await principal(["audit", await slug_de(db, tenant_a)]) == 0

    saida = capsys.readouterr().out
    assert "config.min_similarity" in saida and "rafael" in saida
    assert "0.5" in saida and "0.9" not in saida  # nada da empresa B


# --- US5 cenário 3: valor inválido recusa tudo ------------------------------------------------------
async def test_valor_invalido_recusa_toda_a_alteracao_e_preserva_o_anterior(
    db: AsyncEngine, tenant_a: uuid.UUID, capsys: pytest.CaptureFixture[str]
) -> None:
    slug = await slug_de(db, tenant_a)

    codigo = await principal(
        ["config", "set", slug, *OPERADOR, "handoff_ttl_minutos=30", "min_similarity=2"]
    )

    assert codigo == 1
    erro = capsys.readouterr().err
    assert "min_similarity:" in erro and "handoff_ttl_minutos" not in erro
    cfg = await _config(db, tenant_a)
    assert cfg.min_similarity == 0.30 and cfg.handoff_ttl_minutos == 60  # type: ignore[attr-defined]
    assert await consultar(db, "SELECT 1 FROM audit_log WHERE entidade = 'config'") == []


async def test_aplicar_alteracoes_levanta_config_invalida(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    with pytest.raises(ConfigInvalida):
        await _alterar(tenant_a, limite_mensagens_por_minuto=0)
    with pytest.raises(ConfigInvalida):
        await _alterar(tenant_a, campo_inventado=1)
    assert await consultar(db, "SELECT 1 FROM audit_log") == []


async def test_config_set_aplica_e_config_show_mostra(
    db: AsyncEngine, tenant_a: uuid.UUID, capsys: pytest.CaptureFixture[str]
) -> None:
    slug = await slug_de(db, tenant_a)

    assert (
        await principal(
            [
                "config",
                "set",
                slug,
                *OPERADOR,
                "limite_desconto_percentual=5",
                'tom_de_voz="Formal"',
            ]
        )
        == 0
    )
    assert "2 campo(s) alterado(s)" in capsys.readouterr().out

    assert await principal(["config", "show", slug]) == 0
    saida = capsys.readouterr().out
    assert "limite_desconto_percentual" in saida and "5" in saida and "Formal" in saida

    assert await principal(["config", "set", slug, *OPERADOR, "limite_desconto_percentual=5"]) == 0
    assert "nenhuma alteracao" in capsys.readouterr().out


async def test_config_set_exige_operador() -> None:
    assert await principal(["config", "set", "qualquer", "min_similarity=0.5"]) == 2


# --- FR-008: o modelo padrão não muda ----------------------------------------------------------------
async def test_editar_uma_empresa_nao_altera_o_modelo_padrao(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    antes = nova_config_padrao()

    await _alterar(tenant_a, topicos_proibidos=["x"], palavras_gatilho=["y"], min_similarity=0.9)

    assert nova_config_padrao() == antes
    assert CONFIG_PADRAO["topicos_proibidos"] == []
    assert CONFIG_PADRAO["min_similarity"] == 0.30
