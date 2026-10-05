"""CLI de ingestão (T068, T073)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from core.config import settings
from scripts.ingest_docs import principal
from scripts.seed_tenant import NOME_PILOTO, criar_piloto
from tests.conftest import _ADMIN_URL
from tests.fakes.llm import FakeLLMClient
from tests.fakes.pipeline import consultar

DOCS_PILOTO = Path(__file__).resolve().parent.parent / "evals" / "docs_piloto"


@pytest.fixture
def piloto(tenant_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> uuid.UUID:
    monkeypatch.setattr(settings, "pilot_tenant_id", str(tenant_a))
    return tenant_a


async def test_load_de_pasta_imprime_uma_linha_por_documento(
    piloto: uuid.UUID, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.md").write_text("Abrimos aos sábados das 8h às 12h.", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Estacionamento gratuito.", encoding="utf-8")
    (tmp_path / "c.xlsx").write_bytes(b"x")
    assert await principal(["load", str(tmp_path)], FakeLLMClient()) == 0
    linhas = capsys.readouterr().out.strip().splitlines()
    assert len(linhas) == 3
    assert (
        linhas[0].startswith("a.md  OK  versao=1  trechos=1  tokens_embedding=")
        and "custo_usd=" in linhas[0]
    )
    assert linhas[2] == "c.xlsx  NAO_SUPORTADO"


async def test_load_de_arquivo_unico_e_reexecucao_inalterada(
    piloto: uuid.UUID, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arquivo = tmp_path / "faq.md"
    arquivo.write_text("Conteúdo do FAQ.", encoding="utf-8")
    await principal(["load", str(arquivo)], FakeLLMClient())
    capsys.readouterr()
    assert await principal(["load", str(arquivo)], FakeLLMClient()) == 0
    assert capsys.readouterr().out.strip() == "faq.md  INALTERADO  versao=1"


async def test_saida_nao_contem_o_conteudo_do_arquivo(
    piloto: uuid.UUID, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "x.md").write_text("SEGREDO-INTERNO-123", encoding="utf-8")
    await principal(["load", str(tmp_path)], FakeLLMClient())
    assert "SEGREDO-INTERNO-123" not in capsys.readouterr().out


async def test_codigo_de_saida_1_quando_algum_documento_falha(
    piloto: uuid.UUID, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.md").write_text("Conteúdo.", encoding="utf-8")
    assert await principal(["load", str(tmp_path)], FakeLLMClient(falhar_embedding=True)) == 1
    assert "a.md  FALHA  erro=embedding:timeout" in capsys.readouterr().out


async def test_arquivo_sem_texto_conta_como_falha(
    piloto: uuid.UUID, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "vazio.txt").write_text("  ", encoding="utf-8")
    assert await principal(["load", str(tmp_path)], FakeLLMClient()) == 1
    assert "vazio.txt  SEM_TEXTO" in capsys.readouterr().out


async def test_caminho_inexistente(
    piloto: uuid.UUID, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await principal(["load", str(tmp_path / "nao-existe")], FakeLLMClient()) == 1
    assert "não encontrado" in capsys.readouterr().err


async def test_list(piloto: uuid.UUID, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "faq_clinica.md").write_text("Conteúdo do FAQ.", encoding="utf-8")
    await principal(["load", str(tmp_path)], FakeLLMClient())
    capsys.readouterr()
    assert await principal(["list"]) == 0
    linhas = capsys.readouterr().out.strip().splitlines()
    assert linhas[0].split() == ["nome_origem", "versao", "trechos", "atualizado_em"]
    assert linhas[1].split()[:3] == ["faq_clinica.md", "1", "1"] and linhas[1].split()[3].endswith(
        "Z"
    )


async def test_remove_com_yes(
    piloto: uuid.UUID, tmp_path: Path, capsys: pytest.CaptureFixture[str], db: AsyncEngine
) -> None:
    (tmp_path / "a.md").write_text("Conteúdo.", encoding="utf-8")
    await principal(["load", str(tmp_path)], FakeLLMClient())
    capsys.readouterr()
    assert await principal(["remove", "a.md", "--yes"]) == 0
    assert "a.md  REMOVIDO" in capsys.readouterr().out
    assert await consultar(db, "SELECT 1 FROM knowledge_documents") == []
    assert await principal(["remove", "a.md", "--yes"]) == 1


async def test_remove_pede_confirmacao(
    piloto: uuid.UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db: AsyncEngine,
) -> None:
    (tmp_path / "a.md").write_text("Conteúdo.", encoding="utf-8")
    await principal(["load", str(tmp_path)], FakeLLMClient())
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert await principal(["remove", "a.md"]) == 1
    assert len(await consultar(db, "SELECT 1 FROM knowledge_documents")) == 1
    monkeypatch.setattr("builtins.input", lambda _: "s")
    assert await principal(["remove", "a.md"]) == 0
    assert await consultar(db, "SELECT 1 FROM knowledge_documents") == []


async def test_documentos_do_piloto_sao_ingeridos(piloto: uuid.UUID, db: AsyncEngine) -> None:
    assert await principal(["load", str(DOCS_PILOTO)], FakeLLMClient()) == 0
    nomes = {
        d.nome_origem for d in await consultar(db, "SELECT nome_origem FROM knowledge_documents")
    }
    assert nomes == {"faq_clinica.md", "horarios.md", "politicas.md", "precos.md"}


async def test_seed_tenant_cria_piloto_com_config_completa_e_e_idempotente(db: AsyncEngine) -> None:
    primeiro = await criar_piloto(_ADMIN_URL)
    segundo = await criar_piloto(_ADMIN_URL)
    assert primeiro == segundo
    cfg = (await consultar(db, "SELECT * FROM tenant_config WHERE tenant_id = :t", t=primeiro))[0]
    assert cfg.router_confidence_threshold == 0.6 and cfg.min_similarity == 0.30
    assert cfg.confianca_minima_handoff == 0.7 and cfg.limite_desconto_percentual == 10.0
    assert "procon" in cfg.palavras_gatilho and "garantia de resultado" in cfg.topicos_proibidos
    assert (await consultar(db, "SELECT nome_empresa FROM tenants"))[0].nome_empresa == NOME_PILOTO
