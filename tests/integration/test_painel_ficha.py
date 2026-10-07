"""Ficha da empresa contra a base e contrato das rotas da ficha (spec 004, T045 e T046; FR-016 a FR-019)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from core.painel.agregacao import inicio_da_hora, recalcular_empresa
from core.tenancy.ciclo_vida import TRANSICOES, Estado
from db.models import AuditLog, ReadinessCheck
from tests.conftest import criar_conexao
from tests.fakes.painel import AdminApi, chaves_proibidas
from tests.integration.test_painel_agregacao import popular_a, popular_b

pytestmark = pytest.mark.integration

H12 = inicio_da_hora(datetime.now(UTC)) - timedelta(hours=28)


async def slug_de(db: AsyncEngine, t: uuid.UUID) -> str:
    async with db.connect() as conn:
        return str(
            (
                await conn.execute(text("SELECT slug FROM tenants WHERE id = :t"), {"t": t})
            ).scalar_one()
        )


async def preparar(db: AsyncEngine, a: uuid.UUID, b: uuid.UUID) -> str:
    await popular_a(db, a, H12)
    await popular_b(db, b, H12)
    for t in (a, b):
        await recalcular_empresa(t, H12 - timedelta(hours=1), H12 + timedelta(hours=3))
    return await slug_de(db, a)


async def test_ficha_confere_com_a_base(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    slug = await preparar(db, tenant_a, tenant_b)
    conexao = await criar_conexao(db, tenant_a, "inst-a-wa")
    async with AsyncSession(db) as s:
        s.add_all(
            [
                ReadinessCheck(
                    tenant_id=tenant_a,
                    operador="ana",
                    tipo="prontidao",
                    config_ok=True,
                    documentos_ok=True,
                    conexao_ok=False,
                    conversa_teste_ok=True,
                    aprovado=False,
                ),
                ReadinessCheck(
                    tenant_id=tenant_a,
                    operador="ana",
                    tipo="conversa_teste",
                    conversa_teste_ok=True,
                    aprovado=True,
                ),
                AuditLog(
                    tenant_id=tenant_a,
                    entidade="conexao",
                    campo="credencial",
                    valor_anterior=None,
                    valor_novo="<atualizada>",
                    operador="ana",
                ),
            ]
        )
        await s.commit()

    r = await admin_api.get(f"/admin/empresas/{slug}", params={"periodo": "7d"})
    assert r.status_code == 200
    f = r.json()
    assert chaves_proibidas(f) == []
    assert conexao.api_key not in r.text and conexao.webhook_secret not in r.text
    assert "TEXTO-QUE-NAO-PODE-VAZAR" not in r.text and "TELEFONE-SECRETO" not in r.text

    emp = f["empresa"]
    assert (emp["slug"], emp["estado"], emp["versao"], emp["plano"]) == (
        slug,
        "ativo",
        1,
        "recepcionista",
    )
    assert emp["encerrada_em"] is None and emp["dados_apagados_em"] is None
    assert f["conexao"] == {
        "canal": "whatsapp",
        "provedor": "evolution",
        "instancia": "inst-a-wa",
        "verificada_em": None,
        "credenciais": "configuradas",
    }
    assert f["base"] == {"documentos": 1, "trechos": 4}
    assert f["prontidao"]["aprovada"] is False and f["prontidao"]["operador"] == "ana"
    assert {i["id"]: i["ok"] for i in f["prontidao"]["itens"]} == {
        "config": True,
        "documentos": True,
        "conexao": False,
        "conversa_teste": True,
    }
    assert f["ultimo_teste"]["aprovado"] is True
    assert f["acoes_permitidas"] == [
        {"para": "suspenso", "rotulo": "Suspender"},
        {"para": "encerrado", "rotulo": "Encerrar"},
    ]

    a = f["atendimento"]  # só a empresa A: nada da B
    assert a["mensagens"] == {"lead": 3, "agente": 3, "humano": 1, "nao_texto": 1}
    assert a["conversas"] == {
        "abertas": 1,
        "handoff": 1,
        "resolvidas": 0,
        "por_canal": {"whatsapp": 2},
    }
    assert a["taxa_handoff_pct"] == pytest.approx(3 / 2 * 100)
    assert a["motivos_handoff"] == [
        {"motivo": "falha_canal", "total": 1},
        {"motivo": "nao_texto", "total": 1},
        {"motivo": "palavra_gatilho:procon", "total": 1},
    ]
    assert a["resposta_media_s"] == pytest.approx(14.7, abs=0.05)  # (3 s + 40 s + 1 s) / 3
    assert a["resposta_p95_s"] == 55.0  # 3 respostas: 1 s, 3 s e 40 s; o balde de 55 s cobre 95%
    assert a["intencoes"] == {"agendar": 1}
    assert a["bloqueios_guardrail"] == 1 and a["falhas_envio"] == 1

    c = f["custo"]
    assert c["total_usd"] == pytest.approx(0.0115, abs=1e-4)
    assert c["por_finalidade"] == {"roteador": 0.001, "suporte": 0.01, "embedding": 0.0005}
    assert c["por_modelo"] == {"m-barato": 0.001, "m-forte": 0.01, "m-emb": 0.0005}
    assert c["por_conversa_usd"] == pytest.approx(0.0115 / 2, abs=1e-3)
    assert (c["tokens_entrada"], c["tokens_saida"]) == (640, 60)
    assert c["margem_usd"] is None and c["orcamento_pct"] is None  # planos sem preço: nunca zero


async def test_acoes_permitidas_vem_da_tabela_de_transicoes(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    slug = await slug_de(db, tenant_a)
    for estado in Estado:
        async with db.begin() as conn:
            await conn.execute(
                text("UPDATE tenants SET status = :s WHERE id = :t"),
                {"s": estado.value, "t": tenant_a},
            )
        f = (await admin_api.get(f"/admin/empresas/{slug}")).json()
        assert [a["para"] for a in f["acoes_permitidas"]] == [d.value for d in TRANSICOES[estado]]
        if estado is Estado.SUSPENSO:
            assert f["acoes_permitidas"][0]["rotulo"] == "Retomar"
        if estado is Estado.EM_CONFIGURACAO:
            assert f["acoes_permitidas"][0]["rotulo"] == "Ativar"


async def test_ficha_de_empresa_com_dados_apagados(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    slug = await slug_de(db, tenant_a)
    async with db.begin() as conn:
        await conn.execute(
            text(
                "UPDATE tenants SET status='encerrado', encerrado_em=now(), dados_apagados_em=now() WHERE id=:t"
            ),
            {"t": tenant_a},
        )
    f = (await admin_api.get(f"/admin/empresas/{slug}")).json()
    assert f["atendimento"] is None and f["custo"] is None and f["base"] is None
    assert f["empresa"]["dados_apagados_em"] is not None and f["acoes_permitidas"] == []
    serie = (await admin_api.get(f"/admin/empresas/{slug}/serie")).json()
    assert serie["pontos"] == []


async def test_serie_da_empresa_nao_mistura_empresas(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    slug = await preparar(db, tenant_a, tenant_b)
    s = (await admin_api.get(f"/admin/empresas/{slug}/serie", params={"periodo": "7d"})).json()
    assert len(s["pontos"]) == 7 and s["fuso"] == "America/Sao_Paulo"
    assert (
        sum(p["recebidas"] for p in s["pontos"]) == 3 and sum(p["agente"] for p in s["pontos"]) == 3
    )
    assert (
        sum(p["humano"] for p in s["pontos"]) == 1 and sum(p["handoffs"] for p in s["pontos"]) == 3
    )
    assert sum(p["custo_usd"] for p in s["pontos"]) == pytest.approx(0.0115, abs=1e-4)
    assert (
        len(
            (
                await admin_api.get(f"/admin/empresas/{slug}/serie", params={"periodo": "hoje"})
            ).json()["pontos"]
        )
        <= 8
    )


async def test_configuracao_traz_os_campos_do_formulario(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    slug = await slug_de(db, tenant_a)
    r = await admin_api.get(f"/admin/empresas/{slug}/configuracao")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["versao"] == 1 and corpo["estado"] == "ativo"
    assert set(corpo["configuracao"]) == {
        "tom_de_voz",
        "horario_funcionamento",
        "limite_desconto_percentual",
        "topicos_proibidos",
        "confianca_minima_handoff",
        "palavras_gatilho",
        "router_confidence_threshold",
        "min_similarity",
        "handoff_ttl_minutos",
        "limite_mensagens_por_minuto",
    }
    assert corpo["configuracao"]["tom_de_voz"] == "Cordial e direto."


async def test_auditoria_pagina_e_nunca_mostra_valor_de_credencial(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    slug = await slug_de(db, tenant_a)
    async with AsyncSession(db) as s:
        for i in range(25):
            s.add(
                AuditLog(tenant_id=tenant_a, entidade="config", campo=f"campo{i}", operador="ana")
            )
        s.add(
            AuditLog(
                tenant_id=tenant_a,
                entidade="conexao",
                campo="credencial",
                valor_novo="<atualizada>",
                operador="ana",
            )
        )
        s.add(AuditLog(tenant_id=tenant_b, entidade="config", campo="da-outra", operador="bia"))
        await s.commit()
    p1 = (await admin_api.get(f"/admin/empresas/{slug}/auditoria", params={"tamanho": 20})).json()
    p2 = (
        await admin_api.get(
            f"/admin/empresas/{slug}/auditoria", params={"tamanho": 20, "pagina": 2}
        )
    ).json()
    assert p1["total"] == 26 and len(p1["itens"]) == 20 and len(p2["itens"]) == 6
    campos = [i["campo"] for i in p1["itens"] + p2["itens"]]
    assert "da-outra" not in campos and len(set(campos)) == 26
    cred = next(i for i in p1["itens"] + p2["itens"] if i["campo"] == "credencial")
    assert cred["valor_novo"] == "<atualizada>"
    assert set(p1["itens"][0]) == {
        "criado_em",
        "entidade",
        "campo",
        "valor_anterior",
        "valor_novo",
        "operador",
    }


@pytest.mark.parametrize(
    "caminho",
    ["", "/serie", "/configuracao", "/auditoria"],
)
async def test_empresa_inexistente_devolve_404(admin_api: AdminApi, caminho: str) -> None:
    r = await admin_api.get(f"/admin/empresas/nao-existe{caminho}")
    assert r.status_code == 404 and r.json()["codigo"] == "empresa_nao_encontrada"


@pytest.mark.parametrize(
    "slug", ["MAIUSCULA", "com_underline", "a" * 64, "'; drop table tenants;--"]
)
async def test_slug_mal_formado_nunca_chega_ao_banco(admin_api: AdminApi, slug: str) -> None:
    r = await admin_api.get(f"/admin/empresas/{slug}")
    assert r.status_code in (400, 404)
    assert "drop table" not in r.text
