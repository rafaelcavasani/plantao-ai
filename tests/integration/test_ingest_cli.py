"""CLI de ingestão (T068, T073)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from scripts.ingest_docs import principal
from tests.conftest import criar_tenant
from tests.fakes.llm import FakeLLMClient
from tests.fakes.pipeline import consultar, slug_de

DOCS_PILOTO = Path(__file__).resolve().parent.parent / "evals" / "docs_piloto"


@pytest_asyncio.fixture
async def piloto(db: AsyncEngine, tenant_a: uuid.UUID) -> str:
    """O `slug` da empresa: a CLI não tem empresa padrão."""
    return await slug_de(db, tenant_a)


async def test_load_de_pasta_imprime_uma_linha_por_documento(
    piloto: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.md").write_text("Abrimos aos sábados das 8h às 12h.", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Estacionamento gratuito.", encoding="utf-8")
    (tmp_path / "c.xlsx").write_bytes(b"x")
    assert await principal(["load", "--tenant", piloto, str(tmp_path)], FakeLLMClient()) == 0
    linhas = capsys.readouterr().out.strip().splitlines()
    assert len(linhas) == 3
    assert (
        linhas[0].startswith("a.md  OK  versao=1  trechos=1  tokens_embedding=")
        and "custo_usd=" in linhas[0]
    )
    assert linhas[2] == "c.xlsx  NAO_SUPORTADO"


async def test_load_de_arquivo_unico_e_reexecucao_inalterada(
    piloto: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arquivo = tmp_path / "faq.md"
    arquivo.write_text("Conteúdo do FAQ.", encoding="utf-8")
    await principal(["load", "--tenant", piloto, str(arquivo)], FakeLLMClient())
    capsys.readouterr()
    assert await principal(["load", "--tenant", piloto, str(arquivo)], FakeLLMClient()) == 0
    assert capsys.readouterr().out.strip() == "faq.md  INALTERADO  versao=1"


async def test_saida_nao_contem_o_conteudo_do_arquivo(
    piloto: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "x.md").write_text("SEGREDO-INTERNO-123", encoding="utf-8")
    await principal(["load", "--tenant", piloto, str(tmp_path)], FakeLLMClient())
    assert "SEGREDO-INTERNO-123" not in capsys.readouterr().out


async def test_codigo_de_saida_1_quando_algum_documento_falha(
    piloto: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.md").write_text("Conteúdo.", encoding="utf-8")
    assert (
        await principal(
            ["load", "--tenant", piloto, str(tmp_path)], FakeLLMClient(falhar_embedding=True)
        )
        == 1
    )
    assert "a.md  FALHA  erro=embedding:timeout" in capsys.readouterr().out


async def test_arquivo_sem_texto_conta_como_falha(
    piloto: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "vazio.txt").write_text("  ", encoding="utf-8")
    assert await principal(["load", "--tenant", piloto, str(tmp_path)], FakeLLMClient()) == 1
    assert "vazio.txt  SEM_TEXTO" in capsys.readouterr().out


async def test_caminho_inexistente(
    piloto: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        await principal(["load", "--tenant", piloto, str(tmp_path / "nao-existe")], FakeLLMClient())
        == 1
    )
    assert "não encontrado" in capsys.readouterr().err


async def test_list(piloto: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "faq_clinica.md").write_text("Conteúdo do FAQ.", encoding="utf-8")
    await principal(["load", "--tenant", piloto, str(tmp_path)], FakeLLMClient())
    capsys.readouterr()
    assert await principal(["list", "--tenant", piloto]) == 0
    linhas = capsys.readouterr().out.strip().splitlines()
    assert linhas[0].split() == ["nome_origem", "versao", "trechos", "atualizado_em"]
    assert linhas[1].split()[:3] == ["faq_clinica.md", "1", "1"] and linhas[1].split()[3].endswith(
        "Z"
    )


async def test_remove_com_yes(
    piloto: str, tmp_path: Path, capsys: pytest.CaptureFixture[str], db: AsyncEngine
) -> None:
    (tmp_path / "a.md").write_text("Conteúdo.", encoding="utf-8")
    await principal(["load", "--tenant", piloto, str(tmp_path)], FakeLLMClient())
    capsys.readouterr()
    assert await principal(["remove", "--tenant", piloto, "a.md", "--yes"]) == 0
    assert "a.md  REMOVIDO" in capsys.readouterr().out
    assert await consultar(db, "SELECT 1 FROM knowledge_documents") == []
    assert await principal(["remove", "--tenant", piloto, "a.md", "--yes"]) == 1


async def test_remove_pede_confirmacao(
    piloto: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db: AsyncEngine,
) -> None:
    (tmp_path / "a.md").write_text("Conteúdo.", encoding="utf-8")
    await principal(["load", "--tenant", piloto, str(tmp_path)], FakeLLMClient())
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert await principal(["remove", "--tenant", piloto, "a.md"]) == 1
    assert len(await consultar(db, "SELECT 1 FROM knowledge_documents")) == 1
    monkeypatch.setattr("builtins.input", lambda _: "s")
    assert await principal(["remove", "--tenant", piloto, "a.md"]) == 0
    assert await consultar(db, "SELECT 1 FROM knowledge_documents") == []


async def test_documentos_do_piloto_sao_ingeridos(piloto: str, db: AsyncEngine) -> None:
    assert await principal(["load", "--tenant", piloto, str(DOCS_PILOTO)], FakeLLMClient()) == 0
    nomes = {
        d.nome_origem for d in await consultar(db, "SELECT nome_origem FROM knowledge_documents")
    }
    assert nomes == {"faq_clinica.md", "horarios.md", "politicas.md", "precos.md"}


async def test_sem_tenant_sai_com_2_e_nada_e_gravado(
    piloto: str, tmp_path: Path, capsys: pytest.CaptureFixture[str], db: AsyncEngine
) -> None:
    (tmp_path / "a.md").write_text("Conteúdo.", encoding="utf-8")
    for argv in (["load", str(tmp_path)], ["list"], ["remove", "a.md", "--yes"]):
        assert await principal(argv, FakeLLMClient()) == 2
        assert "--tenant" in capsys.readouterr().err
    assert await consultar(db, "SELECT 1 FROM knowledge_documents") == []


async def test_empresa_inexistente_sai_com_1(
    db: AsyncEngine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await principal(["list", "--tenant", "nao-existe"]) == 1
    assert "nao encontrada" in capsys.readouterr().err


async def test_empresa_encerrada_e_recusada_e_nada_e_gravado(
    db: AsyncEngine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    await criar_tenant(db, "Encerrada", slug="empresa-encerrada", status="encerrado")
    (tmp_path / "a.md").write_text("Conteúdo.", encoding="utf-8")
    assert (
        await principal(["load", "--tenant", "empresa-encerrada", str(tmp_path)], FakeLLMClient())
        == 1
    )
    assert "encerrada" in capsys.readouterr().err
    assert await consultar(db, "SELECT 1 FROM knowledge_documents") == []


async def test_documentos_ficam_so_na_empresa_indicada(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID, tmp_path: Path
) -> None:
    (tmp_path / "a.md").write_text("Conteúdo da A.", encoding="utf-8")
    assert (
        await principal(
            ["load", "--tenant", await slug_de(db, tenant_a), str(tmp_path)], FakeLLMClient()
        )
        == 0
    )
    donos = {r.tenant_id for r in await consultar(db, "SELECT tenant_id FROM knowledge_documents")}
    assert donos == {tenant_a}
