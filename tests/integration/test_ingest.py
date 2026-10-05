"""Ingestão de documentos (T067)."""

from __future__ import annotations

import io
import uuid
from decimal import Decimal

import pytest
from pypdf import PdfWriter
from sqlalchemy.ext.asyncio import AsyncEngine

from core.rag import ingest
from core.rag.ingest import ingerir_documento, listar_documentos, remover_documento
from core.rag.retrieve import buscar_trechos
from tests.fakes.llm import FakeLLMClient
from tests.fakes.pipeline import consultar

TEXTO = "Horário de atendimento: aos sábados abrimos das 8h às 12h.\n\nEstacionamento gratuito para clientes."


async def _ingerir(
    db: AsyncEngine, tenant: uuid.UUID, nome: str, conteudo: bytes, llm: FakeLLMClient | None = None
):  # type: ignore[no-untyped-def]
    return await ingerir_documento(
        llm or FakeLLMClient(), tenant_id=tenant, nome_origem=nome, conteudo=conteudo
    )


async def test_documento_novo_cria_versao_1_com_trechos_e_embeddings(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    r = await _ingerir(db, tenant_a, "faq.md", TEXTO.encode())
    assert (r.status, r.versao) == ("ok", 1) and r.trechos >= 1 and r.tokens_embedding > 0
    assert r.custo_usd >= Decimal(0)
    doc = (await consultar(db, "SELECT * FROM knowledge_documents"))[0]
    assert doc.nome_origem == "faq.md" and doc.versao == 1 and doc.num_trechos == r.trechos
    assert (
        len(await consultar(db, "SELECT 1 FROM tenant_knowledge WHERE embedding IS NOT NULL"))
        == r.trechos
    )


async def test_mesmo_conteudo_devolve_inalterado_sem_novo_embedding(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _ingerir(db, tenant_a, "faq.md", TEXTO.encode())
    llm = FakeLLMClient()
    r = await _ingerir(db, tenant_a, "faq.md", TEXTO.encode(), llm)
    assert (r.status, r.versao) == ("inalterado", 1) and llm.embeds == []


async def test_conteudo_diferente_substitui_trechos_e_incrementa_versao(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _ingerir(db, tenant_a, "faq.md", TEXTO.encode())
    novo = "Preço da limpeza dental: R$ 150,00 com agendamento."
    r = await _ingerir(db, tenant_a, "faq.md", novo.encode())
    assert (r.status, r.versao) == ("ok", 2)
    textos = [
        x.chunk_texto for x in await consultar(db, "SELECT chunk_texto FROM tenant_knowledge")
    ]
    assert textos == [novo]  # nada da versão antiga sobrou
    assert len(await consultar(db, "SELECT 1 FROM knowledge_documents")) == 1


async def test_busca_apos_atualizacao_so_enxerga_a_versao_nova(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _ingerir(db, tenant_a, "h.md", "Abrimos aos sábados das 8h às 12h.".encode())
    await _ingerir(db, tenant_a, "h.md", "Abrimos aos sábados das 9h às 13h.".encode())
    trechos = await buscar_trechos(
        FakeLLMClient(), tenant_id=tenant_a, pergunta="Abrimos aos sábados?"
    )
    assert [t.texto for t in trechos] == ["Abrimos aos sábados das 9h às 13h."]


async def test_texto_vazio_devolve_sem_texto(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    assert (await _ingerir(db, tenant_a, "vazio.txt", b"   \n")).status == "sem_texto"
    assert await consultar(db, "SELECT 1 FROM knowledge_documents") == []


async def test_pdf_sem_texto_devolve_sem_texto(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    escritor = PdfWriter()
    escritor.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    escritor.write(buffer)
    assert (await _ingerir(db, tenant_a, "scan.pdf", buffer.getvalue())).status == "sem_texto"


async def test_pdf_corrompido_devolve_falha_sem_vazar_conteudo(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    r = await _ingerir(db, tenant_a, "ruim.pdf", b"isto nao e um pdf")
    assert r.status == "falha" and r.erro is not None and r.erro.startswith("leitura:")


async def test_extensao_nao_suportada(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    assert (await _ingerir(db, tenant_a, "planilha.xlsx", b"x")).status == "nao_suportado"


async def test_arquivo_acima_de_5mb(
    db: AsyncEngine, tenant_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest, "TAMANHO_MAXIMO_BYTES", 10)
    assert (await _ingerir(db, tenant_a, "grande.txt", b"x" * 11)).status == "arquivo_grande"


async def test_falha_de_embedding_nao_cria_nada(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    r = await _ingerir(db, tenant_a, "faq.md", TEXTO.encode(), FakeLLMClient(falhar_embedding=True))
    assert r.status == "falha" and r.erro == "embedding:timeout"
    assert await consultar(db, "SELECT 1 FROM knowledge_documents") == []


async def test_falha_de_embedding_mantem_a_versao_anterior_intacta(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await _ingerir(db, tenant_a, "faq.md", TEXTO.encode())
    antes = await consultar(db, "SELECT chunk_texto FROM tenant_knowledge ORDER BY chunk_indice")
    r = await _ingerir(
        db,
        tenant_a,
        "faq.md",
        b"conteudo novo que vai falhar",
        FakeLLMClient(falhar_embedding=True),
    )
    assert r.status == "falha"
    assert (
        await consultar(db, "SELECT chunk_texto FROM tenant_knowledge ORDER BY chunk_indice")
        == antes
    )
    assert (await consultar(db, "SELECT versao FROM knowledge_documents"))[0].versao == 1


async def test_lotes_de_embedding(
    db: AsyncEngine, tenant_a: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest, "LOTE_EMBEDDING", 2)
    llm = FakeLLMClient()
    texto = "\n\n".join(f"Parágrafo {i}. " + "palavra " * 120 for i in range(6))
    r = await _ingerir(db, tenant_a, "longo.md", texto.encode(), llm)
    assert r.status == "ok" and r.trechos > 2
    assert len(llm.embeds) == -(-r.trechos // 2) and all(len(lote) <= 2 for lote in llm.embeds)


async def test_documentos_de_tenants_diferentes_com_o_mesmo_nome_nao_colidem(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    ra = await _ingerir(db, tenant_a, "faq.md", b"Conteudo da clinica A.")
    rb = await _ingerir(db, tenant_b, "faq.md", b"Conteudo da clinica B.")
    assert ra.status == rb.status == "ok"
    assert [d.nome_origem for d in await listar_documentos(tenant_a)] == ["faq.md"]


async def test_listar_e_remover(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    await _ingerir(db, tenant_a, "b.md", b"Segundo documento.")
    await _ingerir(db, tenant_a, "a.md", TEXTO.encode())
    assert [d.nome_origem for d in await listar_documentos(tenant_a)] == ["a.md", "b.md"]
    assert await remover_documento(tenant_a, "a.md") is True
    assert await remover_documento(tenant_a, "a.md") is False
    assert [d.nome_origem for d in await listar_documentos(tenant_a)] == ["b.md"]
    assert {
        x.documento_origem
        for x in await consultar(db, "SELECT documento_origem FROM tenant_knowledge")
    } == {"b.md"}


async def test_tenant_b_nao_remove_documento_do_tenant_a(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await _ingerir(db, tenant_a, "faq.md", TEXTO.encode())
    assert await remover_documento(tenant_b, "faq.md") is False
    assert len(await listar_documentos(tenant_a)) == 1
