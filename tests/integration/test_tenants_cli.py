"""CLI `scripts.tenants` (T042; contracts/tenants-cli.md): saídas, códigos e `--operador` obrigatório."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from core.llm.ports import Finalidade
from core.ports.channel import EstadoConexao
from scripts.tenants import principal
from tests.fakes.channel import FakeChannel
from tests.fakes.conhecimento import json_roteador, json_suporte
from tests.fakes.llm import FakeLLMClient
from tests.fakes.onboarding import CHAVE_ENVIO, SEGREDO_ENTREGA, escrever_empresa
from tests.fakes.pipeline import consultar

DOCUMENTOS = {"horarios.md": "Horário de atendimento: aos sábados abrimos das 08:00 às 12:00."}
TESTE = {"pergunta": "Qual o horário de atendimento aos sábados?", "esperado": ["08:00", "12:00"]}
OPERADOR = ["--operador", "rafael"]


def _llm_suporte() -> FakeLLMClient:
    return FakeLLMClient(
        {
            Finalidade.ROTEADOR: [json_roteador("suporte", 0.95)],
            Finalidade.SUPORTE: [json_suporte("Aos sábados atendemos das 08:00 às 12:00.", 0.95)],
        }
    )


def _arquivo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **extras: object) -> Path:
    return escrever_empresa(
        tmp_path,
        monkeypatch,
        documentos=DOCUMENTOS,
        teste=TESTE,
        **extras,  # type: ignore[arg-type]
    )


async def _criar(arquivo: Path) -> int:
    return await principal(["create", "--file", str(arquivo), *OPERADOR], FakeLLMClient())


async def test_create_imprime_passos_e_proximo_passo(
    db: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await _criar(_arquivo(tmp_path, monkeypatch)) == 0

    linhas = capsys.readouterr().out.splitlines()
    assert linhas[0].startswith("Empresa: clinica-nova (em_configuracao)")
    assert linhas[0].rstrip().endswith("[novo]")
    nomes = [linha.split()[1] for linha in linhas[1:7]]
    assert nomes == ["empresa", "configuracao", "conexao", "credenciais", "documentos", "resumo"]
    assert all(" OK " in linha for linha in linhas[1:7])
    assert "instancia: clinica-nova" in linhas[3]
    assert "1 ok, 0 inalterados, 0 falhas" in linhas[5] and "custo_usd=" in linhas[5]
    assert linhas[-1].startswith("Total: ") and linhas[-1].endswith(
        "Proximo passo: readiness clinica-nova"
    )


async def test_create_repetido_diz_existente_e_inalterado(
    db: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arquivo = _arquivo(tmp_path, monkeypatch)
    await _criar(arquivo)
    capsys.readouterr()
    assert await _criar(arquivo) == 0
    saida = capsys.readouterr().out
    assert "[existente]" in saida.splitlines()[0]
    assert "0 ok, 1 inalterados, 0 falhas" in saida and "inalteradas" in saida


async def test_create_com_falha_de_documento_sai_com_1(
    db: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arquivo = _arquivo(tmp_path, monkeypatch)
    codigo = await principal(
        ["create", "--file", str(arquivo), *OPERADOR], FakeLLMClient(falhar_embedding=True)
    )
    saida = capsys.readouterr().out
    assert codigo == 1 and "FALHA" in saida and "horarios.md  FALHA  erro=embedding:" in saida


async def test_arquivo_invalido_sai_com_2_e_lista_um_erro_por_campo(
    db: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arquivo = escrever_empresa(
        tmp_path,
        monkeypatch,
        slug="Slug Ruim",
        configuracao={"confianca_minima_handoff": 3},
    )
    assert await principal(["create", "--file", str(arquivo), *OPERADOR], FakeLLMClient()) == 2
    err = capsys.readouterr().err
    assert "slug:" in err and "configuracao.confianca_minima_handoff:" in err
    assert await consultar(db, "SELECT 1 FROM tenants") == []


async def test_instancia_em_uso_sai_com_1(
    db: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _criar(_arquivo(tmp_path, monkeypatch))
    capsys.readouterr()
    outra = _arquivo(tmp_path, monkeypatch, slug="outra-clinica", instance="clinica-nova")
    assert await _criar(outra) == 1
    assert "ja esta em uso por outra empresa" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["create", "--file", "x.yml"],
        ["readiness", "clinica-nova"],
        ["test", "clinica-nova", "--file", "x.yml"],
        ["activate", "clinica-nova"],
    ],
)
async def test_operador_e_obrigatorio_nos_comandos_que_alteram(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert await principal(argv, FakeLLMClient(), FakeChannel()) == 2
    assert "--operador" in capsys.readouterr().err


async def test_sem_comando_ou_comando_desconhecido_sai_com_2() -> None:
    assert await principal([]) == 2
    assert await principal(["apagar-tudo"]) == 2


async def test_readiness_reprovada_lista_pendencias_e_sai_com_1(
    db: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _criar(_arquivo(tmp_path, monkeypatch))
    capsys.readouterr()
    canal = FakeChannel(estado_padrao=EstadoConexao.DESCONECTADA)

    assert await principal(["readiness", "clinica-nova", *OPERADOR], channel=canal) == 1

    linhas = capsys.readouterr().out.splitlines()
    assert linhas[0] == "Prontidao de clinica-nova"
    assert linhas[1].split()[:3] == ["configuracao", "completa", "OK"]
    assert (
        linhas[2].split()[:3] == ["documentos", "indexados", "OK"] and "1 documentos" in linhas[2]
    )
    assert linhas[3].split()[:3] == ["conexao", "verificada", "FALTA"]
    assert "instancia desconectada (estado: desconectada)" in linhas[3]
    assert linhas[4].split()[:3] == ["conversa", "de", "teste"] and "FALTA" in linhas[4]
    assert linhas[-1] == "Resultado: REPROVADA (2 pendencias)"


async def test_fluxo_completo_create_test_activate(
    db: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arquivo = _arquivo(tmp_path, monkeypatch)
    await _criar(arquivo)
    canal = FakeChannel()

    assert await principal(["activate", "clinica-nova", *OPERADOR], channel=canal) == 1
    recusada = capsys.readouterr()
    assert recusada.out.splitlines()[-1] == "Ativacao recusada."

    assert (
        await principal(["test", "clinica-nova", "--file", str(arquivo), *OPERADOR], _llm_suporte())
        == 0
    )
    teste = capsys.readouterr().out
    assert "APROVADA" in teste and "sabados" not in teste.lower() and "08:00" not in teste

    assert await principal(["activate", "clinica-nova", *OPERADOR], channel=canal) == 0
    saida = capsys.readouterr().out
    assert "Resultado: APROVADA" in saida and "Empresa clinica-nova ativada." in saida
    assert (await consultar(db, "SELECT status FROM tenants"))[0].status == "ativo"
    assert await consultar(db, "SELECT 1 FROM messages") == []  # o teste não grava mensagem


async def test_teste_reprovado_por_handoff_sai_com_1(
    db: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arquivo = _arquivo(tmp_path, monkeypatch)
    await _criar(arquivo)
    llm = FakeLLMClient({Finalidade.ROTEADOR: [json_roteador("venda", 0.95)]})

    assert await principal(["test", "clinica-nova", "--file", str(arquivo), *OPERADOR], llm) == 1

    assert "REPROVADA (handoff:" in capsys.readouterr().out
    linha = (await consultar(db, "SELECT aprovado, tipo FROM readiness_checks"))[0]
    assert (linha.tipo, linha.aprovado) == ("conversa_teste", False)


async def test_teste_com_arquivo_de_outra_empresa_sai_com_2(
    db: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arquivo = _arquivo(tmp_path, monkeypatch)
    await _criar(arquivo)
    assert (
        await principal(["test", "outra", "--file", str(arquivo), *OPERADOR], _llm_suporte()) == 2
    )


async def test_empresa_inexistente_sai_com_1(
    db: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await principal(["status", "nao-existe"]) == 1
    assert "nao encontrada" in capsys.readouterr().err
    assert await principal(["readiness", "nao-existe", *OPERADOR], channel=FakeChannel()) == 1


async def test_list_e_status(
    db: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await _criar(_arquivo(tmp_path, monkeypatch))
    capsys.readouterr()

    assert await principal(["list"]) == 0
    linhas = capsys.readouterr().out.splitlines()
    assert linhas[0].split() == ["slug", "estado", "ativada_em", "instancia", "verificada_em"]
    assert linhas[1].split()[:2] == ["clinica-nova", "em_configuracao"]
    assert "clinica-nova" in linhas[1].split()[3:]

    assert await principal(["status", "clinica-nova"]) == 0
    saida = capsys.readouterr().out
    assert "Estado: em_configuracao" in saida and "Documentos: 1" in saida
    assert "instancia=clinica-nova" in saida and "Ultimo teste: nenhuma" in saida


async def test_nenhuma_saida_traz_credenciais(
    db: AsyncEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arquivo = _arquivo(tmp_path, monkeypatch)
    await _criar(arquivo)
    canal = FakeChannel()
    for argv in (
        ["list"],
        ["status", "clinica-nova"],
        ["readiness", "clinica-nova", *OPERADOR],
        ["activate", "clinica-nova", *OPERADOR],
    ):
        await principal(argv, _llm_suporte(), canal)
    saida = capsys.readouterr()
    assert CHAVE_ENVIO not in saida.out + saida.err
    assert SEGREDO_ENTREGA not in saida.out + saida.err
