"""Contrato das rotas de leitura da API de operação (spec 004, T034 e T046)."""

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from core.painel.agregacao import inicio_da_hora, recalcular_empresa
from tests.fakes.painel import AdminApi, chaves_proibidas
from tests.integration.test_painel_agregacao import popular_a

pytestmark = pytest.mark.contract

H12 = inicio_da_hora(datetime.now(UTC)) - timedelta(hours=28)


async def test_visao_geral_tem_o_formato_do_contrato(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await popular_a(db, tenant_a, H12)
    await recalcular_empresa(tenant_a, H12, H12 + timedelta(hours=2))
    r = await admin_api.get("/admin/visao-geral", params={"periodo": "7d"})
    assert r.status_code == 200
    v = r.json()
    assert set(v) == {
        "periodo",
        "fuso",
        "atualizado_em",
        "empresas_por_estado",
        "totais",
        "serie",
        "funil",
        "atencao",
    }
    assert set(v["totais"]) == {
        "mensagens",
        "conversas",
        "taxa_handoff_pct",
        "custo_usd",
        "margem_usd",
    }
    assert set(v["totais"]["mensagens"]) == {"valor", "anterior", "recebidas", "agente", "humano"}
    assert set(v["funil"]) == {"conversas", "respondidas_agente", "handoff", "resolvidas_humano"}
    assert set(v["empresas_por_estado"]) == {
        "ativo",
        "em_configuracao",
        "suspenso",
        "encerrado",
        "total",
    }
    assert chaves_proibidas(v) == []


@pytest.mark.parametrize("periodo", ["ontem", "", "90d"])
async def test_periodo_invalido_devolve_400(admin_api: AdminApi, periodo: str) -> None:
    r = await admin_api.get("/admin/visao-geral", params={"periodo": periodo})
    assert (
        r.status_code == 400
        and r.json()["codigo"] == "validacao"
        and "periodo" in r.json()["campos"]
    )


@pytest.mark.parametrize(
    "params",
    [
        {"ordem": "slug; DROP TABLE tenants"},
        {"ordem": "conteudo"},
        {"sentido": "up"},
        {"estado": "x"},
        {"tamanho": 101},
        {"tamanho": 0},
        {"pagina": 0},
    ],
)
async def test_parametros_de_lista_invalidos_devolvem_400(
    admin_api: AdminApi, params: dict[str, object]
) -> None:
    r = await admin_api.get("/admin/empresas", params=params)
    assert r.status_code == 400, params
    assert "DROP TABLE" not in r.text  # o valor recebido nunca volta na resposta


async def test_lista_de_empresas_tem_o_formato_do_contrato(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await popular_a(db, tenant_a, H12)
    await recalcular_empresa(tenant_a, H12, H12 + timedelta(hours=2))
    r = await admin_api.get("/admin/empresas", params={"periodo": "7d", "tamanho": 100})
    assert r.status_code == 200
    corpo = r.json()
    assert set(corpo) == {"total", "pagina", "tamanho", "atualizado_em", "itens"}
    assert set(corpo["itens"][0]) == {
        "slug",
        "nome",
        "nicho",
        "plano",
        "estado",
        "criada_em",
        "ativada_em",
        "mensagens",
        "conversas_abertas",
        "handoffs",
        "ultima_mensagem",
        "custo_usd",
        "orcamento_usd",
        "orcamento_pct",
        "conexao",
        "documentos",
        "atencao",
    }
    assert set(corpo["itens"][0]["ultima_mensagem"]) == {"em", "remetente"}


async def test_exportacao_csv_tem_as_colunas_do_contrato(
    admin_api: AdminApi, tenant_a: uuid.UUID
) -> None:
    r = await admin_api.get("/admin/empresas.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    cabecalho = next(csv.reader(io.StringIO(r.text.lstrip("\ufeff")), delimiter=";"))
    assert cabecalho == [
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


async def test_planos_listados_sem_valor_inventado(admin_api: AdminApi) -> None:
    r = await admin_api.get("/admin/planos")
    assert r.status_code == 200
    assert [p["chave"] for p in r.json()] == [
        "recepcionista",
        "recepcionista_agendador",
        "pacote_completo",
    ]
    assert all(
        set(p) == {"chave", "nome", "orcamento_mensal_usd", "preco_mensal_usd"} for p in r.json()
    )
