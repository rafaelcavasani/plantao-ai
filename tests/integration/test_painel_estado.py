"""Mudança de estado pelo painel (spec 004, T053 e T054; US3, FR-002, FR-007, FR-021 a FR-023)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from core.config import settings
from db.models import KnowledgeDocument, ReadinessCheck
from tests.conftest import criar_conexao, criar_tenant
from tests.fakes.painel import LEITOR, OPERADOR, AdminApi

pytestmark = [pytest.mark.integration, pytest.mark.contract]


async def info(db: AsyncEngine, t: uuid.UUID) -> dict[str, object]:
    async with db.connect() as conn:
        linha = (
            (
                await conn.execute(
                    text(
                        "SELECT slug, nome_empresa, status, versao, encerrado_em FROM tenants WHERE id = :t"
                    ),
                    {"t": t},
                )
            )
            .mappings()
            .one()
        )
    return dict(linha)


async def auditoria(db: AsyncEngine, t: uuid.UUID) -> list[dict[str, object]]:
    async with db.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT entidade, campo, valor_anterior, valor_novo, operador FROM audit_log "
                        "WHERE tenant_id = :t ORDER BY criado_em, id"
                    ),
                    {"t": t},
                )
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


def corpo(versao: int, para: str, **extra: object) -> dict[str, object]:
    return {"versao": versao, "para": para, **extra}


async def test_suspender_e_retomar_gravam_operador_motivo_e_versao(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    slug = (await info(db, tenant_a))["slug"]
    r = await admin_api.post(
        f"/admin/empresas/{slug}/estado", json=corpo(1, "suspenso", motivo="inadimplência")
    )
    assert r.status_code == 200, r.text
    assert r.json()["empresa"]["estado"] == "suspenso" and r.json()["empresa"]["versao"] == 2
    assert [a["para"] for a in r.json()["acoes_permitidas"]] == ["ativo", "encerrado"]
    assert r.json()["acoes_permitidas"][0]["rotulo"] == "Retomar"

    linhas = await auditoria(db, tenant_a)
    estado = next(a for a in linhas if a["campo"] == "status")
    assert (estado["entidade"], estado["valor_anterior"], estado["valor_novo"]) == (
        "estado",
        "ativo",
        "suspenso",
    )
    assert estado["operador"] == OPERADOR  # o e-mail da sessão, nunca texto livre
    assert next(a for a in linhas if a["campo"] == "motivo")["valor_novo"] == "inadimplência"

    r2 = await admin_api.post(f"/admin/empresas/{slug}/estado", json=corpo(2, "ativo"))
    assert r2.status_code == 200 and r2.json()["empresa"]["estado"] == "ativo"
    assert r2.json()["empresa"]["versao"] == 3
    assert (await info(db, tenant_a))["status"] == "ativo"


async def test_encerrar_exige_o_nome_exato(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    dados = await info(db, tenant_a)
    slug, nome = dados["slug"], dados["nome_empresa"]
    for errado in (None, "", str(nome).lower(), f" {nome}x", "Outra"):
        r = await admin_api.post(
            f"/admin/empresas/{slug}/estado", json=corpo(1, "encerrado", confirmacao=errado)
        )
        assert r.status_code == 400 and "confirmacao" in r.json()["campos"], errado
    assert (await info(db, tenant_a))["status"] == "ativo"

    r = await admin_api.post(
        f"/admin/empresas/{slug}/estado",
        json=corpo(1, "encerrado", confirmacao=nome, motivo="pediu"),
    )
    assert r.status_code == 200 and r.json()["empresa"]["estado"] == "encerrado"
    assert r.json()["acoes_permitidas"] == []
    assert (await info(db, tenant_a))["encerrado_em"] is not None


async def test_transicao_fora_da_tabela_devolve_409_com_o_estado_atual(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    dados = await info(db, tenant_a)
    slug = dados["slug"]
    await admin_api.post(
        f"/admin/empresas/{slug}/estado",
        json=corpo(1, "encerrado", confirmacao=dados["nome_empresa"]),
    )
    r = await admin_api.post(f"/admin/empresas/{slug}/estado", json=corpo(2, "ativo"))
    assert r.status_code == 409 and r.json()["codigo"] == "transicao_invalida"
    assert r.json()["estado_atual"] == "encerrado" and r.json()["permitidos"] == []
    # ativo -> ativo também não existe.
    outra = await criar_tenant(db, "Outra")
    slug2 = (await info(db, outra))["slug"]
    r = await admin_api.post(f"/admin/empresas/{slug2}/estado", json=corpo(1, "ativo"))
    assert r.status_code == 409 and r.json()["permitidos"] == ["suspenso", "encerrado"]


async def test_versao_antiga_devolve_conflito_com_os_valores_atuais(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    slug = (await info(db, tenant_a))["slug"]
    r = await admin_api.post(f"/admin/empresas/{slug}/estado", json=corpo(99, "suspenso"))
    assert r.status_code == 409 and r.json()["codigo"] == "conflito_versao"
    atual = r.json()["atual"]
    assert (
        atual["versao"] == 1 and atual["estado"] == "ativo" and atual["configuracao"]["tom_de_voz"]
    )
    assert (await info(db, tenant_a))["status"] == "ativo"


async def test_papel_de_leitura_nao_altera_nada(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    slug = (await info(db, tenant_a))["slug"]
    for caminho, json in (
        (f"/admin/empresas/{slug}/estado", corpo(1, "suspenso")),
        (f"/admin/empresas/{slug}/prontidao", None),
    ):
        r = await admin_api.post(caminho, email=LEITOR, json=json)
        assert r.status_code == 403 and r.json()["codigo"] == "sem_permissao"
    assert (await info(db, tenant_a))["status"] == "ativo"
    assert await auditoria(db, tenant_a) == []


async def test_post_de_estado_sem_origin_e_recusado(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    slug = (await info(db, tenant_a))["slug"]
    r = await admin_api.post(
        f"/admin/empresas/{slug}/estado", origem=None, json=corpo(1, "suspenso")
    )
    assert r.status_code == 403 and r.json()["codigo"] == "origem_invalida"
    assert (await info(db, tenant_a))["status"] == "ativo"


async def test_limite_de_taxa_por_operador(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "painel_escrita_por_minuto", 3)
    slug = (await info(db, tenant_a))["slug"]
    codigos = [
        (await admin_api.post(f"/admin/empresas/{slug}/estado", json=corpo(1, "ativo"))).status_code
        for _ in range(4)
    ]
    assert codigos == [
        409,
        409,
        409,
        429,
    ]  # 409 = transição inválida (ativo -> ativo), conta como tentativa
    r = await admin_api.post(f"/admin/empresas/{slug}/estado", json=corpo(1, "ativo"))
    assert (
        r.status_code == 429
        and r.headers["retry-after"] == "60"
        and r.json()["codigo"] == "limite_excedido"
    )


async def test_ativar_com_prontidao_reprovada_nao_ativa_e_mostra_os_itens(
    admin_api: AdminApi, db: AsyncEngine
) -> None:
    t = await criar_tenant(db, "Nova", status="em_configuracao")
    slug = (await info(db, t))["slug"]
    r = await admin_api.post(f"/admin/empresas/{slug}/estado", json=corpo(1, "ativo"))
    assert r.status_code == 409 and r.json()["codigo"] == "prontidao_reprovada"
    itens = {i["id"]: i["ok"] for i in r.json()["itens"]}
    assert len(itens) == 4 and not all(itens.values())
    dados = await info(db, t)
    assert dados["status"] == "em_configuracao" and dados["versao"] == 1  # nada mudou
    async with db.connect() as conn:  # mas a verificação ficou registrada, como no CLI
        n = (
            await conn.execute(
                text("SELECT count(*) FROM readiness_checks WHERE tenant_id = :t"), {"t": t}
            )
        ).scalar_one()
    assert n == 1


async def test_ativar_com_prontidao_aprovada(admin_api: AdminApi, db: AsyncEngine) -> None:
    t = await criar_tenant(db, "Pronta", status="em_configuracao")
    await criar_conexao(db, t, "inst-pronta")
    async with AsyncSession(db) as s:
        s.add(KnowledgeDocument(tenant_id=t, nome_origem="faq.md", content_hash="h", num_trechos=3))
        await s.commit()
        s.add(
            ReadinessCheck(
                tenant_id=t,
                operador="x",
                tipo="conversa_teste",
                conversa_teste_ok=True,
                aprovado=True,
            )
        )
        await s.commit()
    slug = (await info(db, t))["slug"]

    pr = await admin_api.post(f"/admin/empresas/{slug}/prontidao")
    assert pr.status_code == 200 and pr.json()["aprovada"] is True and len(pr.json()["itens"]) == 4

    r = await admin_api.post(f"/admin/empresas/{slug}/estado", json=corpo(1, "ativo"))
    assert r.status_code == 200, r.text
    assert (
        r.json()["empresa"]["estado"] == "ativo" and r.json()["empresa"]["ativada_em"] is not None
    )
    assert r.json()["conexao"]["verificada_em"] is not None  # a verificação gravou `verificada_em`


async def test_prontidao_de_empresa_inexistente_devolve_404(admin_api: AdminApi) -> None:
    r = await admin_api.post("/admin/empresas/nao-existe/prontidao")
    assert r.status_code == 404
