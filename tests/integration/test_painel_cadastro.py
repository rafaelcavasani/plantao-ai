"""Cadastro e edição de empresas pelo painel (spec 004, T060 a T064; US4, FR-024 e FR-034 a FR-041)."""

import base64
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from core.painel.remessas import processar_remessa
from core.tenancy.onboarding import carregar_arquivo, criar_ou_continuar
from db.admin import admin_session
from tests.conftest import criar_conexao, criar_tenant
from tests.fakes.llm import FakeLLMClient
from tests.fakes.onboarding import CHAVE_ENVIO, escrever_empresa
from tests.fakes.painel import LEITOR, OPERADOR, AdminApi, chaves_proibidas
from tests.fakes.pipeline import consultar

pytestmark = [pytest.mark.integration, pytest.mark.contract]

CONFIG = {
    "tom_de_voz": "Cordial e direto.",
    "horario_funcionamento": {"seg_sex": "08:00-18:00", "sabado": "08:00-12:00"},
}
SEGREDO = "entrega-" + "x" * 40


def novo(slug: str = "clinica-nova", **extra: Any) -> dict[str, Any]:
    corpo: dict[str, Any] = {
        "nome": f"Empresa {slug}",
        "slug": slug,
        "nicho": "clinica_odontologica",
        "configuracao": dict(CONFIG),
        "conexao": {"instancia": slug, "segredo_entrega": SEGREDO, "chave_envio": CHAVE_ENVIO},
    }
    corpo.update(extra)
    return corpo


async def estado_da_empresa(db: AsyncEngine, slug: str) -> dict[str, Any]:
    t = (await consultar(db, f"SELECT * FROM tenants WHERE slug = '{slug}'"))[0]
    cfg = (await consultar(db, f"SELECT * FROM tenant_config WHERE tenant_id = '{t.id}'"))[0]
    conexoes = await consultar(db, f"SELECT * FROM channel_connections WHERE tenant_id = '{t.id}'")
    cred = await consultar(db, f"SELECT * FROM channel_credentials WHERE tenant_id = '{t.id}'")
    audit = await consultar(
        db,
        f"SELECT entidade, campo, valor_anterior, valor_novo FROM audit_log WHERE tenant_id = '{t.id}' ORDER BY campo",
    )
    return {
        "status": t.status,
        "nome": t.nome_empresa,
        "nicho": t.nicho,
        "plano": t.plano,
        "config": {
            "tom": cfg.tom_de_voz,
            "horario": cfg.horario_funcionamento,
            "desconto": cfg.limite_desconto_percentual,
            "gatilho": sorted(cfg.palavras_gatilho),
        },
        "conexao": [(c.canal, c.provedor, c.instance_name) for c in conexoes],
        "credenciais": len(cred),
        "audit": [(a.entidade, a.campo, a.valor_anterior, a.valor_novo) for a in audit],
        "id": t.id,
    }


# --- T060: paridade com o CLI ---------------------------------------------------------------------


async def test_criar_pela_api_equivale_a_criar_pelo_cli(
    admin_api: AdminApi, db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arquivo = escrever_empresa(tmp_path, monkeypatch, slug="via-cli", documentos=None)
    await criar_ou_continuar(
        carregar_arquivo(arquivo), operador="ana", llm=FakeLLMClient(), sessao_admin=admin_session
    )
    r = await admin_api.post("/admin/empresas", json=novo("via-api"))
    assert r.status_code == 201, r.text
    assert (
        r.json()["empresa"]["estado"] == "em_configuracao"
        and r.json()["empresa"]["slug"] == "via-api"
    )
    assert r.json()["conexao"]["instancia"] == "via-api"

    cli, api = await estado_da_empresa(db, "via-cli"), await estado_da_empresa(db, "via-api")

    def neutro(audit: list[tuple[Any, ...]], slug: str) -> list[tuple[Any, ...]]:
        return [tuple("<slug>" if v == slug else v for v in linha) for linha in audit]

    for campo in ("status", "nicho", "plano", "config", "credenciais"):
        assert cli[campo] == api[campo], campo
    # Mesma auditoria (campo a campo), tirando só o nome da instância, que carrega o slug.
    assert neutro(cli["audit"], "via-cli") == neutro(api["audit"], "via-api")
    assert [c[:2] for c in cli["conexao"]] == [c[:2] for c in api["conexao"]]
    assert api["status"] == "em_configuracao"


async def test_repetir_o_cadastro_completa_sem_duplicar(
    admin_api: AdminApi, db: AsyncEngine
) -> None:
    sem_conexao = novo("repete", conexao=None)
    r1 = await admin_api.post("/admin/empresas", json=sem_conexao)
    assert r1.status_code == 201 and r1.json()["conexao"] is None
    r2 = await admin_api.post("/admin/empresas", json=novo("repete"))  # agora com a conexão
    assert r2.status_code == 201 and r2.json()["conexao"]["instancia"] == "repete"
    r3 = await admin_api.post(
        "/admin/empresas", json=novo("repete")
    )  # e uma terceira vez, sem mudar nada
    assert r3.status_code == 201
    assert len(await consultar(db, "SELECT 1 FROM tenants")) == 1
    assert len(await consultar(db, "SELECT 1 FROM channel_connections")) == 1
    auditoria1 = len(await consultar(db, "SELECT 1 FROM audit_log"))
    await admin_api.post("/admin/empresas", json=novo("repete"))
    assert len(await consultar(db, "SELECT 1 FROM audit_log")) == auditoria1  # idempotente


async def test_slug_de_outra_empresa_nao_e_sobrescrito(
    admin_api: AdminApi, db: AsyncEngine
) -> None:
    t = await criar_tenant(db, "Existente", slug="ja-existe")  # ativa, não é a mesma empresa
    r = await admin_api.post("/admin/empresas", json=novo("ja-existe", nome="Outra empresa"))
    assert r.status_code == 409 and r.json()["codigo"] == "slug_em_uso"
    assert "slug" in r.json()["campos"]
    # Mesmo nome em empresa ativa também não "continua": só vale para empresas ainda em configuração.
    r = await admin_api.post("/admin/empresas", json=novo("ja-existe", nome="Existente"))
    assert r.status_code == 409
    assert (await consultar(db, f"SELECT nome_empresa FROM tenants WHERE id = '{t}'"))[0][
        0
    ] == "Existente"


# --- T061: validações -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug",
    [
        "Maiuscula",
        "com_underline",
        "-comeca",
        "termina-",
        "dois--hifens",
        "a" * 64,
        "ab",
        "espaço aqui",
    ],
)
async def test_slug_invalido_devolve_400_no_campo(
    admin_api: AdminApi, db: AsyncEngine, slug: str
) -> None:
    r = await admin_api.post("/admin/empresas", json=novo(slug))
    assert r.status_code == 400 and r.json()["codigo"] == "validacao"
    assert "slug" in r.json()["campos"]
    assert await consultar(db, "SELECT 1 FROM tenants") == []


async def test_instancia_de_outra_empresa_devolve_409_e_nada_e_criado(
    admin_api: AdminApi, db: AsyncEngine
) -> None:
    dona = await criar_tenant(db, "Dona")
    await criar_conexao(db, dona, "instancia-ocupada")
    r = await admin_api.post(
        "/admin/empresas",
        json=novo(
            "nova-aqui",
            conexao={
                "instancia": "instancia-ocupada",
                "segredo_entrega": SEGREDO,
                "chave_envio": "k",
            },
        ),
    )
    assert r.status_code == 409 and r.json()["codigo"] == "instancia_em_uso"
    assert "conexao.instancia" in r.json()["campos"]
    assert (
        await consultar(db, "SELECT 1 FROM tenants WHERE slug = 'nova-aqui'") == []
    )  # nada pela metade


@pytest.mark.parametrize(
    ("conexao", "campo"),
    [
        (
            {"instancia": "i", "segredo_entrega": "curto", "chave_envio": "k"},
            "conexao.segredo_entrega",
        ),
        (
            {"instancia": "i", "segredo_entrega": "x" * 31, "chave_envio": "k"},
            "conexao.segredo_entrega",
        ),
        ({"instancia": "i", "segredo_entrega": SEGREDO, "chave_envio": ""}, "conexao.chave_envio"),
        ({"instancia": "", "segredo_entrega": SEGREDO, "chave_envio": "k"}, "conexao.instancia"),
    ],
)
async def test_conexao_invalida_devolve_400_sem_repetir_o_segredo(
    admin_api: AdminApi, db: AsyncEngine, conexao: dict[str, str], campo: str
) -> None:
    r = await admin_api.post("/admin/empresas", json=novo("valida", conexao=conexao))
    assert r.status_code == 400 and campo in r.json()["campos"], r.text
    assert "x" * 31 not in r.text and SEGREDO not in r.text
    assert await consultar(db, "SELECT 1 FROM tenants") == []


@pytest.mark.parametrize(
    ("configuracao", "campo"),
    [
        ({"horario_funcionamento": {"seg": "8h-18h"}}, "configuracao.horario_funcionamento"),
        ({"horario_funcionamento": {"seg": "25:00-26:00"}}, "configuracao.horario_funcionamento"),
        ({"limite_desconto_percentual": 101}, "configuracao.limite_desconto_percentual"),
        ({"limite_desconto_percentual": -1}, "configuracao.limite_desconto_percentual"),
        ({"confianca_minima_handoff": 1.5}, "configuracao.confianca_minima_handoff"),
        ({"limite_mensagens_por_minuto": 0}, "configuracao.limite_mensagens_por_minuto"),
        ({"limite_mensagens_por_minuto": 6001}, "configuracao.limite_mensagens_por_minuto"),
        ({"handoff_ttl_minutos": 1441}, "configuracao.handoff_ttl_minutos"),
        ({"palavras_gatilho": ["ok", " "]}, "configuracao.palavras_gatilho"),
        ({"campo_que_nao_existe": 1}, "configuracao"),
    ],
)
async def test_configuracao_fora_da_faixa_devolve_400_e_nao_cria(
    admin_api: AdminApi, db: AsyncEngine, configuracao: dict[str, Any], campo: str
) -> None:
    r = await admin_api.post("/admin/empresas", json=novo("faixas", configuracao=configuracao))
    assert r.status_code == 400 and any(k.startswith(campo) for k in r.json()["campos"]), r.text
    assert await consultar(db, "SELECT 1 FROM tenants") == []


async def test_dia_fechado_vira_dia_sem_chave(admin_api: AdminApi, db: AsyncEngine) -> None:
    r = await admin_api.post(
        "/admin/empresas",
        json=novo(
            "fechado",
            configuracao={
                "horario_funcionamento": {"seg": "08:00-18:00", "dom": "fechado", "sab": "Fechado"}
            },
        ),
    )
    assert r.status_code == 201, r.text
    h = (await estado_da_empresa(db, "fechado"))["config"]["horario"]
    assert h == {"seg": "08:00-18:00"}


async def test_campo_desconhecido_no_corpo_e_recusado(admin_api: AdminApi) -> None:
    r = await admin_api.post("/admin/empresas", json={**novo("extra"), "status": "ativo"})
    assert r.status_code == 400 and "status" in r.json()["campos"]


async def test_papel_de_leitura_nao_cria(admin_api: AdminApi, db: AsyncEngine) -> None:
    r = await admin_api.post("/admin/empresas", email=LEITOR, json=novo("sem-permissao"))
    assert r.status_code == 403 and await consultar(db, "SELECT 1 FROM tenants") == []


# --- T062: edição ---------------------------------------------------------------------------------


async def test_editar_audita_so_o_que_mudou_e_incrementa_a_versao(
    admin_api: AdminApi, db: AsyncEngine
) -> None:
    criada = (await admin_api.post("/admin/empresas", json=novo("editavel"))).json()
    v = criada["empresa"]["versao"]
    antes = len(await consultar(db, "SELECT 1 FROM audit_log"))
    r = await admin_api.patch(
        "/admin/empresas/editavel",
        json={
            "versao": v,
            "nome": "Nome Novo",
            "configuracao": {"limite_desconto_percentual": 5, "tom_de_voz": "Cordial e direto."},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["alteracoes"] == 2 and r.json()["empresa"]["nome"] == "Nome Novo"
    assert r.json()["empresa"]["versao"] == v + 1
    novas = (
        await consultar(
            db,
            "SELECT campo, valor_anterior, valor_novo, operador FROM audit_log ORDER BY criado_em, id",
        )
    )[antes:]
    assert sorted((n.campo, n.operador) for n in novas) == [
        ("limite_desconto_percentual", OPERADOR),
        ("nome_empresa", OPERADOR),
    ]
    desconto = next(n for n in novas if n.campo == "limite_desconto_percentual")
    assert (desconto.valor_anterior, desconto.valor_novo) == (
        0.0,
        5.0,
    )  # padrão de `nova_config_padrao`


async def test_salvar_sem_alteracoes_nao_mexe_na_versao_nem_na_auditoria(
    admin_api: AdminApi, db: AsyncEngine
) -> None:
    v = (await admin_api.post("/admin/empresas", json=novo("igual"))).json()["empresa"]["versao"]
    antes = len(await consultar(db, "SELECT 1 FROM audit_log"))
    r = await admin_api.patch(
        "/admin/empresas/igual",
        json={
            "versao": v,
            "nome": "Empresa igual",
            "nicho": "clinica_odontologica",
            "configuracao": dict(CONFIG),
        },
    )
    assert (
        r.status_code == 200 and r.json()["alteracoes"] == 0 and r.json()["empresa"]["versao"] == v
    )
    assert len(await consultar(db, "SELECT 1 FROM audit_log")) == antes


async def test_slug_nao_muda(admin_api: AdminApi) -> None:
    await admin_api.post("/admin/empresas", json=novo("fixo"))
    r = await admin_api.patch("/admin/empresas/fixo", json={"versao": 1, "slug": "outro"})
    assert r.status_code == 400 and "slug" in r.json()["campos"]
    ok = await admin_api.patch("/admin/empresas/fixo", json={"versao": 1, "slug": "fixo"})
    assert ok.status_code == 200 and ok.json()["alteracoes"] == 0


async def test_empresa_encerrada_nao_e_editavel_mas_suspensa_e(
    admin_api: AdminApi, db: AsyncEngine
) -> None:
    t = await criar_tenant(db, "Estados", slug="estados")
    async with db.begin() as conn:
        await conn.execute(text("UPDATE tenants SET status = 'suspenso' WHERE id = :t"), {"t": t})
    r = await admin_api.patch(
        "/admin/empresas/estados",
        json={"versao": 1, "configuracao": {"limite_desconto_percentual": 7}},
    )
    assert (
        r.status_code == 200 and r.json()["empresa"]["estado"] == "suspenso"
    )  # editou sem mudar o estado
    async with db.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET status = 'encerrado', encerrado_em = now() WHERE id = :t"),
            {"t": t},
        )
    r = await admin_api.patch("/admin/empresas/estados", json={"versao": 2, "nome": "Tentativa"})
    assert r.status_code == 409 and r.json()["codigo"] == "empresa_encerrada"
    r = await admin_api.put(
        "/admin/empresas/estados/conexao",
        json={"versao": 2, "instancia": "i", "segredo_entrega": SEGREDO, "chave_envio": "k"},
    )
    assert r.status_code == 409 and r.json()["codigo"] == "empresa_encerrada"


async def test_duas_edicoes_simultaneas_a_segunda_recebe_o_conflito(admin_api: AdminApi) -> None:
    await admin_api.post("/admin/empresas", json=novo("corrida"))
    a = await admin_api.patch("/admin/empresas/corrida", json={"versao": 1, "nome": "Primeira"})
    b = await admin_api.patch("/admin/empresas/corrida", json={"versao": 1, "nome": "Segunda"})
    assert a.status_code == 200 and b.status_code == 409 and b.json()["codigo"] == "conflito_versao"
    assert b.json()["atual"]["nome"] == "Primeira" and b.json()["atual"]["versao"] == 2


async def test_substituir_conexao_zera_a_verificacao_e_audita_a_marca(
    admin_api: AdminApi, db: AsyncEngine
) -> None:
    v = (await admin_api.post("/admin/empresas", json=novo("troca"))).json()["empresa"]["versao"]
    async with db.begin() as conn:
        await conn.execute(text("UPDATE channel_connections SET verificada_em = now()"))
    nova_chave = "outra-chave-de-envio-123"
    r = await admin_api.put(
        "/admin/empresas/troca/conexao",
        json={
            "versao": v,
            "instancia": "troca",
            "segredo_entrega": SEGREDO,
            "chave_envio": nova_chave,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["conexao"]["verificada_em"] is None and r.json()["empresa"]["versao"] == v + 1
    assert nova_chave not in r.text and SEGREDO not in r.text
    audit = await consultar(
        db, "SELECT campo, valor_anterior, valor_novo FROM audit_log WHERE campo = 'credencial'"
    )
    assert all(a.valor_novo in (None, "<atualizada>") for a in audit)
    assert nova_chave not in json.dumps([tuple(a) for a in audit])


# --- T063: credenciais nunca saem -----------------------------------------------------------------


async def test_credenciais_nunca_aparecem_em_resposta_nem_em_log(
    admin_api: AdminApi, db: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    chave = "chave-super-secreta-do-canal-999"
    respostas = [
        await admin_api.post(
            "/admin/empresas",
            json=novo(
                "sigilo",
                conexao={"instancia": "sigilo", "segredo_entrega": SEGREDO, "chave_envio": chave},
            ),
        ),
        await admin_api.post(
            "/admin/empresas",
            json=novo(
                "sigilo2",
                conexao={"instancia": "sigilo", "segredo_entrega": SEGREDO, "chave_envio": chave},
            ),
        ),
        await admin_api.post(
            "/admin/empresas",
            json=novo(
                "sigilo3",
                conexao={"instancia": "i3", "segredo_entrega": "curto", "chave_envio": chave},
            ),
        ),
        await admin_api.get("/admin/empresas/sigilo"),
        await admin_api.get("/admin/empresas/sigilo/auditoria"),
        await admin_api.get("/admin/empresas/sigilo/configuracao"),
    ]
    for r in respostas:
        assert chave not in r.text and SEGREDO not in r.text, r.request.url
        if r.status_code < 400:
            assert chaves_proibidas(r.json()) == [], r.request.url
    assert chave not in caplog.text and SEGREDO not in caplog.text
    resumo = (await admin_api.get("/admin/empresas/sigilo")).json()["conexao"]
    assert resumo["credenciais"] == "configuradas"


# --- T064: documentos -----------------------------------------------------------------------------


def arq(nome: str, texto: str = "# Horários\nAtendemos de segunda a sexta.") -> dict[str, str]:
    return {"nome": nome, "conteudo_base64": base64.b64encode(texto.encode()).decode()}


async def test_remessa_enfileira_e_o_job_indexa(admin_api: AdminApi, db: AsyncEngine) -> None:
    await admin_api.post("/admin/empresas", json=novo("docs"))
    r = await admin_api.post(
        "/admin/empresas/docs/documentos",
        json={"arquivos": [arq("faq.md"), arq("precos.txt", "Consulta R$ 150")]},
    )
    assert r.status_code == 202, r.text
    remessa = r.json()["remessa"]
    assert admin_api.fila.jobs[-1][:2] == ("ingerir_remessa", (remessa,))

    pendente = (await admin_api.get(f"/admin/empresas/docs/documentos/remessas/{remessa}")).json()
    assert pendente["estado"] == "processando"

    resultado = await processar_remessa(admin_api.redis, FakeLLMClient(), remessa)
    assert {a["nome"]: a["status"] for a in resultado["arquivos"]} == {
        "faq.md": "ok",
        "precos.txt": "ok",
    }
    pronto = (await admin_api.get(f"/admin/empresas/docs/documentos/remessas/{remessa}")).json()
    assert (
        pronto["estado"] == "concluida"
        and pronto["base"]["documentos"] == 2
        or pronto["base"] is not None
    )
    assert len(await consultar(db, "SELECT 1 FROM knowledge_documents")) == 2
    # Os bytes dos arquivos não ficam no Redis depois de indexados.
    assert [k async for k in admin_api.redis.scan_iter(match="painel:remessa:*:arq:*")] == []

    outra = await admin_api.get(
        f"/admin/empresas/{(await criar_tenant_slug(db))}/documentos/remessas/{remessa}"
    )
    assert outra.status_code == 404  # a remessa só é visível na empresa dona


async def criar_tenant_slug(db: AsyncEngine) -> str:
    t = await criar_tenant(db, "Outra Empresa", slug="outra-empresa")
    return str((await consultar(db, f"SELECT slug FROM tenants WHERE id = '{t}'"))[0][0])


async def test_remessa_recusa_nome_repetido_formato_e_tamanho(admin_api: AdminApi) -> None:
    await admin_api.post("/admin/empresas", json=novo("limites"))
    url = "/admin/empresas/limites/documentos"
    r = await admin_api.post(url, json={"arquivos": [arq("a.md"), arq("a.md")]})
    assert r.status_code == 400 and "arquivos" in r.json()["campos"]
    r = await admin_api.post(url, json={"arquivos": [arq("virus.exe")]})
    assert r.status_code == 415 and r.json()["codigo"] == "formato_nao_suportado"
    r = await admin_api.post(
        url, json={"arquivos": [arq("grande.md", "x" * (2 * 1024 * 1024 + 1))]}
    )
    assert r.status_code == 413 and r.json()["codigo"] == "arquivo_grande"
    ok = await admin_api.post(url, json={"arquivos": [arq("limite.md", "x" * (2 * 1024 * 1024))]})
    assert ok.status_code == 202
    r = await admin_api.post(
        url, json={"arquivos": [{"nome": "x.md", "conteudo_base64": "***não é base64***"}]}
    )
    assert r.status_code == 400
    r = await admin_api.post(url, json={"arquivos": [arq(f"{i}.md") for i in range(11)]})
    assert r.status_code == 400  # no máximo 10 por remessa
    r = await admin_api.post(url, json={"arquivos": []})
    assert r.status_code == 400
    assert (
        len(admin_api.fila.jobs) == 1
    )  # só a remessa válida (a de exatamente 2 MB) foi enfileirada


async def test_remessa_inexistente_ou_expirada_devolve_404(admin_api: AdminApi) -> None:
    await admin_api.post("/admin/empresas", json=novo("expira"))
    r = await admin_api.get(f"/admin/empresas/expira/documentos/remessas/{uuid.uuid4().hex}")
    assert r.status_code == 404 and r.json()["codigo"] == "remessa_nao_encontrada"
    r = await admin_api.get("/admin/empresas/expira/documentos/remessas/nao-e-hex")
    assert r.status_code == 400


async def test_remessa_em_empresa_encerrada_e_recusada(
    admin_api: AdminApi, db: AsyncEngine
) -> None:
    t = await criar_tenant(db, "Fim", slug="fim")
    async with db.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET status = 'encerrado', encerrado_em = now() WHERE id = :t"),
            {"t": t},
        )
    r = await admin_api.post("/admin/empresas/fim/documentos", json={"arquivos": [arq("a.md")]})
    assert r.status_code == 409 and r.json()["codigo"] == "empresa_encerrada"
    assert admin_api.fila.jobs == []


# --- Apagar dados (P3, FR-025) --------------------------------------------------------------------


async def test_apagar_dados_exige_encerrada_e_nome_exato(
    admin_api: AdminApi, db: AsyncEngine
) -> None:
    t = await criar_tenant(db, "Apagavel", slug="apagavel")
    resumo = (await admin_api.get("/admin/empresas/apagavel/apagar-dados/resumo")).json()
    assert (
        resumo["pode_apagar"] is False
        and resumo["estado"] == "ativo"
        and "mensagens" in resumo["contagens"]
    )

    r = await admin_api.post(
        "/admin/empresas/apagavel/apagar-dados", json={"confirmacao": "Apagavel"}
    )
    assert r.status_code == 409 and r.json()["codigo"] == "exclusao_recusada"  # não está encerrada

    await admin_api.post(
        "/admin/empresas/apagavel/estado",
        json={"versao": 1, "para": "encerrado", "confirmacao": "Apagavel"},
    )
    assert (await admin_api.get("/admin/empresas/apagavel/apagar-dados/resumo")).json()[
        "pode_apagar"
    ] is True
    errado = await admin_api.post(
        "/admin/empresas/apagavel/apagar-dados", json={"confirmacao": "apagavel"}
    )
    assert errado.status_code == 409 and "Confirmacao incorreta" in errado.json()["mensagem"]
    assert len(await consultar(db, f"SELECT 1 FROM tenant_config WHERE tenant_id = '{t}'")) == 1

    ok = await admin_api.post(
        "/admin/empresas/apagavel/apagar-dados", json={"confirmacao": "Apagavel"}
    )
    assert ok.status_code == 200, ok.text
    assert await consultar(db, f"SELECT 1 FROM tenant_config WHERE tenant_id = '{t}'") == []
    ficha = (await admin_api.get("/admin/empresas/apagavel")).json()
    assert ficha["empresa"]["dados_apagados_em"] is not None and ficha["atendimento"] is None


async def test_apagar_dados_so_para_operacao(admin_api: AdminApi, db: AsyncEngine) -> None:
    await criar_tenant(db, "Intocavel", slug="intocavel")
    r = await admin_api.get("/admin/empresas/intocavel/apagar-dados/resumo", email=LEITOR)
    assert r.status_code == 403  # o resumo da exclusão é só para quem pode operar
    r = await admin_api.post(
        "/admin/empresas/intocavel/apagar-dados", email=LEITOR, json={"confirmacao": "Intocavel"}
    )
    assert r.status_code == 403
