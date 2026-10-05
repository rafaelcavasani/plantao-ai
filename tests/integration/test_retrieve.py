"""Busca vetorial por tenant (T039)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from core.llm.ports import LLMError
from core.rag.retrieve import buscar_trechos
from tests.fakes.conhecimento import inserir_conhecimento
from tests.fakes.llm import FakeLLMClient

DOCS = {
    "faq.md": [
        "Horário de atendimento: aos sábados abrimos das 8h às 12h.",
        "Limpeza dental custa R$ 150,00 com agendamento.",
        "Estacionamento gratuito para clientes da clínica.",
    ]
}
PERGUNTA = "Qual o horário de atendimento aos sábados?"


async def test_devolve_trechos_do_mais_ao_menos_similar(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await inserir_conhecimento(db, tenant_a, DOCS)
    trechos = await buscar_trechos(
        FakeLLMClient(), tenant_id=tenant_a, pergunta=PERGUNTA, min_similarity=0.0, top_k=3
    )
    assert trechos[0].texto == DOCS["faq.md"][0] and trechos[0].documento == "faq.md"
    similaridades = [t.similaridade for t in trechos]
    assert similaridades == sorted(similaridades, reverse=True) and trechos[0].similaridade > 0.5


async def test_respeita_top_k(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    await inserir_conhecimento(
        db, tenant_a, {"a.md": [f"horário atendimento sábados parte {i}" for i in range(8)]}
    )
    assert (
        len(
            await buscar_trechos(
                FakeLLMClient(), tenant_id=tenant_a, pergunta=PERGUNTA, min_similarity=0.0, top_k=4
            )
        )
        == 4
    )
    assert (
        len(
            await buscar_trechos(
                FakeLLMClient(), tenant_id=tenant_a, pergunta=PERGUNTA, min_similarity=0.0, top_k=2
            )
        )
        == 2
    )


async def test_min_similarity_descarta_trechos_irrelevantes(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await inserir_conhecimento(db, tenant_a, DOCS)
    trechos = await buscar_trechos(
        FakeLLMClient(), tenant_id=tenant_a, pergunta=PERGUNTA, min_similarity=0.30
    )
    assert [t.texto for t in trechos] == [DOCS["faq.md"][0]]
    assert all(t.similaridade >= 0.30 for t in trechos)


async def test_base_vazia_devolve_lista_vazia(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    assert await buscar_trechos(FakeLLMClient(), tenant_id=tenant_a, pergunta=PERGUNTA) == []


async def test_pergunta_sem_relacao_devolve_lista_vazia(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await inserir_conhecimento(db, tenant_a, DOCS)
    assert (
        await buscar_trechos(
            FakeLLMClient(), tenant_id=tenant_a, pergunta="Vocês vendem pizza vegana?"
        )
        == []
    )


async def test_nunca_devolve_trechos_de_outro_tenant(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await inserir_conhecimento(db, tenant_b, DOCS)  # só o tenant B tem a base
    assert (
        await buscar_trechos(
            FakeLLMClient(), tenant_id=tenant_a, pergunta=PERGUNTA, min_similarity=0.0
        )
        == []
    )
    do_b = await buscar_trechos(FakeLLMClient(), tenant_id=tenant_b, pergunta=PERGUNTA)
    assert len(do_b) >= 1


async def test_cada_tenant_ve_o_proprio_conteudo(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    await inserir_conhecimento(
        db, tenant_a, {"a.md": ["Horário de atendimento aos sábados: 8h às 12h."]}
    )
    await inserir_conhecimento(
        db, tenant_b, {"b.md": ["Horário de atendimento aos sábados: 9h às 17h."]}
    )
    a = await buscar_trechos(FakeLLMClient(), tenant_id=tenant_a, pergunta=PERGUNTA)
    b = await buscar_trechos(FakeLLMClient(), tenant_id=tenant_b, pergunta=PERGUNTA)
    assert [t.documento for t in a] == ["a.md"] and [t.documento for t in b] == ["b.md"]


async def test_falha_de_embedding_levanta_llm_error(db: AsyncEngine, tenant_a: uuid.UUID) -> None:
    with pytest.raises(LLMError):
        await buscar_trechos(
            FakeLLMClient(falhar_embedding=True), tenant_id=tenant_a, pergunta=PERGUNTA
        )
