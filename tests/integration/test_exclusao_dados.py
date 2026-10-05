"""Encerramento e exclusão de dados de uma empresa (US6, T075; FR-019, FR-020, SC-008, research R-11).

Banco real (papel da aplicação para os dados, papel administrativo para a marca), Redis falso. A suíte usa três
empresas para provar que apagar C não toca em A nem em B.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from apps.worker.jobs import processar_mensagem
from core.llm.ports import Finalidade
from core.tenancy import ConexaoEmUso, cadastrar_conexao
from core.tenancy.exclusao import ExclusaoRecusada, apagar_dados, encerrar
from db.admin import admin_session
from db.session import tenant_session
from scripts import ingest_docs
from scripts.tenants import principal
from tests.conftest import criar_conexao, criar_tenant
from tests.fakes.channel import FakeChannel
from tests.fakes.conhecimento import inserir_conhecimento, json_roteador, json_suporte
from tests.fakes.isolamento import ENTIDADES_COBERTAS, Dados, popular_todas
from tests.fakes.llm import FakeLLMClient
from tests.fakes.pipeline import consultar, contexto, receber, slug_de

pytestmark = pytest.mark.integration

OPERADOR = ["--operador", "rafael"]
NOME_C = "Clínica C"
# `audit_log` é a trilha que sobrevive à exclusão; as demais tabelas voltam a zero.
TABELAS_DE_DADOS = [t for t in ENTIDADES_COBERTAS if t != "audit_log"]


async def _contagens(db: AsyncEngine, tenant_id: uuid.UUID) -> dict[str, int]:
    saida: dict[str, int] = {}
    for tabela in ENTIDADES_COBERTAS:
        linhas = await consultar(
            db, f"SELECT count(*) AS n FROM {tabela} WHERE tenant_id = :t", t=tenant_id
        )
        saida[tabela] = int(linhas[0].n)
    return saida


async def _dados(db: AsyncEngine, tenant_id: uuid.UUID) -> dict[str, int]:
    """Contagens só das tabelas de dados (a trilha de auditoria cresce com `close` e `purge`)."""
    todas = await _contagens(db, tenant_id)
    return {t: todas[t] for t in TABELAS_DE_DADOS}


def _esperado(dados: Dados) -> dict[str, int]:
    return {t: dados.linhas[t] for t in TABELAS_DE_DADOS}


async def _estado(db: AsyncEngine, tenant_id: uuid.UUID) -> str:
    return str((await consultar(db, "SELECT status FROM tenants WHERE id = :t", t=tenant_id))[0][0])


async def _encerrar(tenant_id: uuid.UUID) -> None:
    async with admin_session() as s:
        await encerrar(s, tenant_id, "rafael")


async def _apagar(
    tenant_id: uuid.UUID,
    nome: str = NOME_C,
    redis: FakeAsyncRedis | None = None,
    drenagem: int = 0,
) -> Any:
    return await apagar_dados(
        admin_session, tenant_id, nome, "rafael", redis=redis, drenagem_segundos=drenagem
    )


async def _trio(
    db: AsyncEngine,
) -> tuple[dict[str, uuid.UUID], dict[uuid.UUID, Dados]]:
    ids = {
        "a": await criar_tenant(db, "Clínica A"),
        "b": await criar_tenant(db, "Clínica B"),
        "c": await criar_tenant(db, NOME_C),
    }
    return ids, await popular_todas(db, ids)


# --- encerrar ------------------------------------------------------------------------------------------
async def test_close_deixa_de_responder_e_mantem_o_numero_reservado(
    db: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    ids, _ = await _trio(db)
    slug = await slug_de(db, ids["c"])
    instancia = (
        await consultar(
            db,
            "SELECT instance_name FROM channel_connections WHERE canal = 'whatsapp' "
            "AND tenant_id = :t",
            t=ids["c"],
        )
    )[0].instance_name

    assert await principal(["close", slug, *OPERADOR]) == 0

    assert "encerrada" in capsys.readouterr().out
    assert await _estado(db, ids["c"]) == "encerrado"
    assert (await consultar(db, "SELECT encerrado_em FROM tenants WHERE id = :t", t=ids["c"]))[
        0
    ].encerrado_em is not None
    async with tenant_session(ids["b"]) as s:  # o número continua reservado (FR-020)
        with pytest.raises(ConexaoEmUso):
            await cadastrar_conexao(
                s,
                ids["b"],
                instance_name=instancia,
                webhook_secret="s" * 40,
                api_key="chave-b",
                operador="rafael",
            )
    assert await _estado(db, ids["a"]) == await _estado(db, ids["b"]) == "ativo"


async def test_close_registra_a_mudanca_de_estado_na_auditoria(db: AsyncEngine) -> None:
    ids, _ = await _trio(db)
    assert await principal(["close", await slug_de(db, ids["c"]), *OPERADOR]) == 0
    linha = (
        await consultar(
            db,
            "SELECT valor_anterior, valor_novo, operador FROM audit_log "
            "WHERE entidade = 'estado' AND tenant_id = :t",
            t=ids["c"],
        )
    )[0]
    assert (linha.valor_anterior, linha.valor_novo, linha.operador) == (
        "ativo",
        "encerrado",
        "rafael",
    )


async def test_close_de_empresa_encerrada_e_recusado(
    db: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    ids, _ = await _trio(db)
    slug = await slug_de(db, ids["c"])
    assert await principal(["close", slug, *OPERADOR]) == 0
    capsys.readouterr()

    assert await principal(["close", slug, *OPERADOR]) == 1
    assert "Transicao invalida: encerrado -> encerrado" in capsys.readouterr().err


async def test_job_em_andamento_durante_o_close_nao_envia_resposta(db: AsyncEngine) -> None:
    tenant_id = await criar_tenant(db, NOME_C)
    await criar_conexao(db, tenant_id, instance_name="inst-c")
    await inserir_conhecimento(
        db, tenant_id, {"faq.md": ["Horário de atendimento: aos sábados abrimos das 8h às 12h."]}
    )
    llm = FakeLLMClient(
        {
            Finalidade.ROTEADOR: [json_roteador("suporte", 0.95)],
            Finalidade.SUPORTE: [json_suporte("Aos sábados atendemos das 8h às 12h.", 0.95)],
        }
    )
    canal = FakeChannel()
    mid, _ = await receber(tenant_id)
    grafo = contexto(llm, canal)["grafo"]

    class GrafoQueEncerra:
        """Encerra a empresa depois de decidir e antes de gravar, como um operador no meio do job."""

        async def executar(self, entrada: Any, config: Any) -> Any:
            decisao = await grafo.executar(entrada, config)
            await _encerrar(tenant_id)
            return decisao

    resultado = await processar_mensagem(
        {"grafo": GrafoQueEncerra(), "channel": canal}, str(tenant_id), str(mid), "c-1"
    )

    assert resultado == "empresa_inativa"
    assert canal.envios == []
    assert await consultar(db, "SELECT 1 FROM messages WHERE responde_a IS NOT NULL") == []


async def test_ingestao_recusa_empresa_encerrada(
    db: AsyncEngine, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    ids, _ = await _trio(db)
    slug = await slug_de(db, ids["c"])
    await _encerrar(ids["c"])
    arquivo = tmp_path / "novo.md"
    arquivo.write_text("Texto novo.", encoding="utf-8")

    assert (
        await ingest_docs.principal(["load", "--tenant", slug, str(arquivo)], FakeLLMClient()) == 1
    )
    assert await ingest_docs.principal(["list", "--tenant", slug]) == 1
    assert "encerrada" in capsys.readouterr().err


# --- apagar: recusas ----------------------------------------------------------------------------------
async def test_purge_exige_empresa_encerrada(db: AsyncEngine) -> None:
    ids, dados = await _trio(db)

    with pytest.raises(ExclusaoRecusada) as info:
        await _apagar(ids["c"])

    assert "encerrada" in str(info.value) and "ativo" in str(info.value)
    assert await _dados(db, ids["c"]) == _esperado(dados[ids["c"]])


@pytest.mark.parametrize("nome", ["", "clínica c", "Clínica", "Clínica C ", "Clínica A"])
async def test_purge_sem_a_confirmacao_exata_nao_apaga_nada(db: AsyncEngine, nome: str) -> None:
    ids, dados = await _trio(db)
    await _encerrar(ids["c"])

    with pytest.raises(ExclusaoRecusada) as info:
        await _apagar(ids["c"], nome)

    assert "confirmacao" in str(info.value).lower()
    assert await _dados(db, ids["c"]) == _esperado(dados[ids["c"]])
    assert (await consultar(db, "SELECT dados_apagados_em FROM tenants WHERE id = :t", t=ids["c"]))[
        0
    ].dados_apagados_em is None


async def test_purge_antes_da_drenagem_recusa_e_diz_quanto_falta(db: AsyncEngine) -> None:
    ids, dados = await _trio(db)
    await _encerrar(ids["c"])

    with pytest.raises(ExclusaoRecusada) as info:
        await _apagar(ids["c"], drenagem=3600)

    assert "drenagem" in str(info.value).lower()
    assert await _dados(db, ids["c"]) == _esperado(dados[ids["c"]])


# --- apagar: sucesso (SC-008) -------------------------------------------------------------------------
async def test_purge_correto_zera_c_e_nao_toca_em_a_nem_em_b(db: AsyncEngine) -> None:
    ids, dados = await _trio(db)
    redis = FakeAsyncRedis()
    await redis.set(f"rl:{ids['c']}:100", 3)
    await redis.set(f"rl:{ids['c']}:101", 1)
    await redis.set(f"rl:{ids['a']}:100", 7)
    await redis.set(f"rl:{ids['b']}:100", 9)
    antes_a, antes_b = await _contagens(db, ids["a"]), await _contagens(db, ids["b"])
    await _encerrar(ids["c"])
    trilha_antes = (await _contagens(db, ids["c"]))["audit_log"]

    resultado = await _apagar(ids["c"], redis=redis)

    depois_c = await _contagens(db, ids["c"])
    assert {t: depois_c[t] for t in TABELAS_DE_DADOS} == dict.fromkeys(TABELAS_DE_DADOS, 0)
    assert (
        depois_c["audit_log"] == trilha_antes + 1
    )  # a trilha sobrevive e ganha a linha da exclusão
    assert await _contagens(db, ids["a"]) == antes_a == dados[ids["a"]].linhas
    assert await _contagens(db, ids["b"]) == antes_b == dados[ids["b"]].linhas
    assert resultado.contagens["mensagens"] == dados[ids["c"]].linhas["messages"]
    assert resultado.contagens["conversas"] == dados[ids["c"]].linhas["conversations"]
    assert resultado.contagens["conexoes"] == dados[ids["c"]].linhas["channel_connections"]
    assert resultado.chaves_redis == 2
    assert sorted(k.decode() for k in await redis.keys("rl:*")) == sorted(
        [f"rl:{ids['a']}:100", f"rl:{ids['b']}:100"]
    )
    await redis.aclose()


async def test_purge_guarda_a_marca_da_empresa_e_a_auditoria_sem_dado_de_cliente(
    db: AsyncEngine,
) -> None:
    ids, _ = await _trio(db)
    slug = await slug_de(db, ids["c"])
    await _encerrar(ids["c"])

    await _apagar(ids["c"])

    marca = (
        await consultar(
            db,
            "SELECT nome_empresa, slug, status, dados_apagados_em FROM tenants WHERE id = :t",
            t=ids["c"],
        )
    )[0]
    assert (marca.nome_empresa, marca.slug, marca.status) == (NOME_C, slug, "encerrado")
    assert marca.dados_apagados_em is not None
    linha = (
        await consultar(
            db,
            "SELECT campo, valor_anterior, valor_novo, operador, criado_em FROM audit_log "
            "WHERE entidade = 'dados' AND tenant_id = :t",
            t=ids["c"],
        )
    )[0]
    assert linha.campo == "exclusao" and linha.operador == "rafael" and linha.criado_em
    assert linha.valor_novo == {"nome_empresa": NOME_C, "slug": slug}
    assert (
        await consultar(
            db, "SELECT 1 FROM audit_log WHERE entidade = 'dados' AND tenant_id <> :t", t=ids["c"]
        )
        == []
    )


async def test_numero_so_e_liberado_depois_do_purge(db: AsyncEngine) -> None:
    ids, _ = await _trio(db)
    instancia = (
        await consultar(
            db,
            "SELECT instance_name FROM channel_connections WHERE canal = 'whatsapp' "
            "AND tenant_id = :t",
            t=ids["c"],
        )
    )[0].instance_name
    await _encerrar(ids["c"])

    async def _usar_na_b() -> None:
        async with tenant_session(ids["b"]) as s:
            await cadastrar_conexao(
                s,
                ids["b"],
                instance_name=instancia,
                webhook_secret="s" * 40,
                api_key="chave-b",
                operador="rafael",
            )

    with pytest.raises(ConexaoEmUso):
        await _usar_na_b()

    await _apagar(ids["c"])
    await _usar_na_b()

    donos = await consultar(
        db, "SELECT tenant_id FROM channel_connections WHERE instance_name = :i", i=instancia
    )
    assert [d.tenant_id for d in donos] == [ids["b"]]


async def test_purge_repetido_e_recusado(db: AsyncEngine) -> None:
    ids, _ = await _trio(db)
    await _encerrar(ids["c"])
    await _apagar(ids["c"])

    with pytest.raises(ExclusaoRecusada) as info:
        await _apagar(ids["c"])

    assert "ja foram apagados" in str(info.value)
    assert len(await consultar(db, "SELECT 1 FROM audit_log WHERE entidade = 'dados'")) == 1


async def test_o_papel_da_aplicacao_nao_apaga_dados_de_outra_empresa(
    db: AsyncEngine,
) -> None:
    ids, dados = await _trio(db)
    await _encerrar(ids["c"])

    await _apagar(ids["c"])
    # B continua legível e completa pelo papel da aplicação (RLS)
    async with tenant_session(ids["b"]) as s:
        n = (await s.execute(text("SELECT count(*) FROM messages"))).scalar_one()
    assert n == dados[ids["b"]].linhas["messages"]


# --- CLI ---------------------------------------------------------------------------------------------
async def test_purge_pela_cli_imprime_contagens_numericas_e_libera_o_numero(
    db: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    ids, dados = await _trio(db)
    slug = await slug_de(db, ids["c"])
    redis = FakeAsyncRedis()
    await principal(["close", slug, *OPERADOR])
    capsys.readouterr()

    assert await principal(["purge", slug, *OPERADOR, "--confirmar", NOME_C], redis=redis) == 0

    linhas = capsys.readouterr().out.splitlines()
    assert linhas[0].startswith("Empresa encerrada ha ") and "drenagem de 0 s cumprida" in linhas[0]
    assert linhas[1].startswith("Apagado: conversas=")
    assert f"mensagens={dados[ids['c']].linhas['messages']}" in linhas[1]
    assert (
        "credenciais=" in linhas[1] and "conexoes=" in linhas[1] and "configuracao=1" in linhas[1]
    )
    assert (
        linhas[2].startswith("Numero (instancia ")
        and "liberado. Auditoria registrada." in linhas[2]
    )
    await redis.aclose()


async def test_purge_pela_cli_recusado_sai_com_1_e_explica(
    db: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    ids, dados = await _trio(db)
    slug = await slug_de(db, ids["c"])
    await principal(["close", slug, *OPERADOR])
    capsys.readouterr()

    assert await principal(["purge", slug, *OPERADOR, "--confirmar", "errado"]) == 1

    assert "confirmacao" in capsys.readouterr().err.lower()
    assert await _dados(db, ids["c"]) == _esperado(dados[ids["c"]])


@pytest.mark.parametrize(
    "argv",
    [["purge", "x", "--confirmar", "Nome"], ["purge", "x", "--operador", "r"], ["close", "x"]],
)
async def test_close_e_purge_exigem_operador_e_confirmacao(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert await principal(argv) == 2
    assert capsys.readouterr().err
