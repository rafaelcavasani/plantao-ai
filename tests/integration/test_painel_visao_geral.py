"""Visão geral e lista de empresas contra a base (spec 004, T033; SC-003, FR-008 a FR-015)."""

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from core.painel import consultas
from core.painel.agregacao import inicio_da_hora, recalcular_empresa
from core.painel.consultas import FiltrosLista
from db import config_planos
from tests.fakes.painel import AdminApi, chaves_proibidas
from tests.integration.test_painel_agregacao import popular_a, popular_b

pytestmark = pytest.mark.integration

AGORA = inicio_da_hora(datetime.now(UTC)) + timedelta(minutes=30)
H12 = AGORA - timedelta(hours=28)  # dentro de 7d e 30d, fora de "hoje" em qualquer horário


async def preparar(db: AsyncEngine, a: uuid.UUID, b: uuid.UUID) -> None:
    await popular_a(db, a, H12)
    await popular_b(db, b, H12)
    for t in (a, b):
        await recalcular_empresa(t, H12 - timedelta(hours=1), H12 + timedelta(hours=3))


async def total_direto(db: AsyncEngine, tabela_sql: str) -> int:
    async with db.connect() as conn:
        return int((await conn.execute(text(tabela_sql))).scalar_one() or 0)


async def test_visao_geral_soma_as_duas_empresas(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await preparar(db, tenant_a, tenant_b)
    v = await consultas.visao_geral("7d", AGORA)

    mensagens = await total_direto(db, "SELECT count(*) FROM messages")
    assert v["totais"]["mensagens"]["valor"] == mensagens == 11  # 7 da A + 4 da B
    assert v["totais"]["mensagens"]["recebidas"] == 7  # A: 3 do contato; B: 4
    assert v["totais"]["mensagens"]["agente"] == 3 and v["totais"]["mensagens"]["humano"] == 1
    assert (
        v["totais"]["conversas"]["valor"]
        == await total_direto(db, "SELECT count(*) FROM conversations")
        == 3
    )
    assert v["totais"]["conversas"]["abertas"] == 2 and v["totais"]["conversas"]["handoff"] == 1
    assert v["totais"]["custo_usd"]["valor"] == pytest.approx(0.0115 + 9.5, abs=1e-4)
    # 3 handoffs / 3 conversas = 100%.
    assert v["totais"]["taxa_handoff_pct"]["valor"] == 100.0
    assert v["empresas_por_estado"] == {
        "ativo": 2,
        "em_configuracao": 0,
        "suspenso": 0,
        "encerrado": 0,
        "total": 2,
    }
    assert v["periodo"] == "7d" and v["fuso"] == "America/Sao_Paulo"


async def test_periodo_anterior_tem_a_mesma_duracao_e_o_hoje_exclui_o_passado(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await preparar(db, tenant_a, tenant_b)
    hoje = await consultas.visao_geral("hoje", AGORA)
    assert hoje["totais"]["mensagens"]["valor"] == 0  # os dados são de 28 h atrás
    j = consultas.janela("7d", AGORA)
    assert (j.fim - j.inicio) <= timedelta(days=7) and (j.inicio - j.anterior_inicio) == timedelta(
        days=7
    )
    j30 = consultas.janela("30d", AGORA)
    assert (j30.inicio - j30.anterior_inicio) == timedelta(days=30)
    jh = consultas.janela("hoje", AGORA)
    assert (jh.inicio - jh.anterior_inicio) == timedelta(days=1)

    # Dado do período anterior entra em `anterior`, não em `valor`.
    antigo = AGORA - timedelta(days=9)
    await popular_a(db, tenant_b, antigo)  # B ganha atividade de 9 dias atrás
    await recalcular_empresa(tenant_b, antigo - timedelta(hours=1), antigo + timedelta(hours=3))
    v = await consultas.visao_geral("7d", AGORA)
    assert v["totais"]["mensagens"]["anterior"] == 7
    assert v["totais"]["mensagens"]["valor"] == 11


async def test_funil_e_serie(db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID) -> None:
    await preparar(db, tenant_a, tenant_b)
    v = await consultas.visao_geral("7d", AGORA)
    f = v["funil"]
    assert f["conversas"] == 3 and f["handoff"] == 3 and f["respondidas_agente"] == 0
    serie = v["serie"]
    assert len(serie) == 7  # um ponto por dia, zeros incluídos
    assert sum(p["recebidas"] for p in serie) == 7 and sum(p["agente"] for p in serie) == 3
    assert sum(p["custo_usd"] for p in serie) == pytest.approx(9.5115, abs=1e-3)
    assert [p["inicio"] for p in serie] == sorted(p["inicio"] for p in serie)
    assert len((await consultas.visao_geral("30d", AGORA))["serie"]) == 10


async def test_margem_indisponivel_quando_algum_plano_nao_tem_preco(
    db: AsyncEngine, tenant_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    await popular_a(db, tenant_a, H12)
    await recalcular_empresa(tenant_a, H12, H12 + timedelta(hours=2))
    v = await consultas.visao_geral("7d", AGORA)
    assert v["totais"]["margem_usd"] == {"valor": None, "disponivel": False}

    monkeypatch.setitem(
        config_planos.PLANOS,
        "recepcionista",
        {"nome": "R", "orcamento_mensal_usd": 100.0, "preco_mensal_usd": 300.0},
    )
    v = await consultas.visao_geral("7d", AGORA)
    assert v["totais"]["margem_usd"]["disponivel"] is True
    assert v["totais"]["margem_usd"]["valor"] == pytest.approx(300 * 7 / 30 - 0.0115, abs=1e-2)


async def test_atencao_lista_a_empresa_certa(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await preparar(db, tenant_a, tenant_b)
    v = await consultas.visao_geral("7d", AGORA)
    por_slug = {a["slug"]: a for a in v["atencao"]}
    assert len(por_slug) == 2  # as duas ficaram 28 h sem mensagens e sem conexão verificada
    for a in por_slug.values():
        assert "sem_atividade" in a["motivos"] and "conexao_nao_verificada" in a["motivos"]


async def test_lista_filtra_ordena_e_pagina(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await preparar(db, tenant_a, tenant_b)
    todos = await consultas.listar_empresas(
        FiltrosLista(periodo="7d", ordem="mensagens", sentido="desc"), AGORA
    )
    assert todos["total"] == 2
    assert [i["mensagens"] for i in todos["itens"]] == [7, 4]

    so_ativos = await consultas.listar_empresas(
        FiltrosLista(periodo="7d", estado="suspenso"), AGORA
    )
    assert so_ativos["total"] == 0

    pag = await consultas.listar_empresas(FiltrosLista(periodo="7d", tamanho=1, pagina=2), AGORA)
    assert pag["total"] == 2 and len(pag["itens"]) == 1

    async with db.begin() as conn:
        slug = (
            await conn.execute(text("SELECT slug FROM tenants WHERE id = :t"), {"t": tenant_a})
        ).scalar_one()
    achado = await consultas.listar_empresas(FiltrosLista(periodo="7d", q=slug[:8].upper()), AGORA)
    assert any(i["slug"] == slug for i in achado["itens"])


async def test_empresa_sem_mensagens_aparece_sem_erro(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    await recalcular_empresa(tenant_a, H12, H12)
    lista = await consultas.listar_empresas(FiltrosLista(periodo="30d"), AGORA)
    item = lista["itens"][0]
    assert item["ultima_mensagem"] is None
    assert (item["mensagens"], item["conversas_abertas"], item["handoffs"], item["custo_usd"]) == (
        0,
        0,
        0,
        0.0,
    )
    assert item["conexao"] == "sem_conexao" and item["orcamento_pct"] is None


async def test_ordenar_por_ultima_mensagem_deixa_as_sem_mensagem_no_fim(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await popular_a(db, tenant_a, H12)
    await recalcular_empresa(tenant_a, H12, H12 + timedelta(hours=2))
    await recalcular_empresa(tenant_b, H12, H12)
    for sentido in ("asc", "desc"):
        lista = await consultas.listar_empresas(
            FiltrosLista(ordem="ultima_mensagem", sentido=sentido), AGORA
        )
        assert lista["itens"][-1]["ultima_mensagem"] is None


async def test_exportacao_csv_tem_colunas_fixas_e_neutraliza_formula(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await popular_a(db, tenant_a, H12)
    await recalcular_empresa(tenant_a, H12, H12 + timedelta(hours=2))
    async with db.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET nome_empresa = '=HYPERLINK(\"x\")' WHERE id = :t"),
            {"t": tenant_a},
        )
    corpo = await consultas.exportar_csv(FiltrosLista(periodo="7d"), AGORA)
    assert corpo.startswith("﻿")
    linhas = list(csv.reader(io.StringIO(corpo.lstrip("﻿")), delimiter=";"))
    assert linhas[0] == [
        "slug",
        "nome",
        "nicho",
        "plano",
        "estado",
        "criada_em",
        "mensagens",
        "conversas_abertas",
        "handoffs",
        "minutos_desde_ultima_mensagem",
        "custo_usd",
    ]
    assert linhas[1][1] == '\'=HYPERLINK("x")'
    assert "TEXTO-QUE-NAO-PODE-VAZAR" not in corpo and "TELEFONE-SECRETO" not in corpo


async def test_api_nao_devolve_chaves_sensiveis(
    admin_api: AdminApi, tenant_a: uuid.UUID, db: AsyncEngine
) -> None:
    await popular_a(db, tenant_a, H12)
    await recalcular_empresa(tenant_a, H12, H12 + timedelta(hours=2))
    for caminho in (
        "/admin/visao-geral?periodo=30d",
        "/admin/empresas?periodo=30d",
        "/admin/planos",
    ):
        r = await admin_api.get(caminho)
        assert r.status_code == 200, caminho
        assert chaves_proibidas(r.json()) == [], caminho
        assert "TEXTO-QUE-NAO-PODE-VAZAR" not in r.text and "TELEFONE-SECRETO" not in r.text
