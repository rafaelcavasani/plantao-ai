"""Continuidade da empresa piloto na migração 0004 (FR-032, SC-007).

Cria uma empresa no schema da 0003 (antes do multi-tenancy), aplica a 0004 e confere que nenhum dado
mudou, que o `slug` foi preenchido e que o `status` foi mapeado.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import _ADMIN_URL, alembic_config, recriar_banco

pytestmark = pytest.mark.integration

PILOTO = uuid.UUID("11111111-1111-1111-1111-111111111111")
CONVERSA = uuid.UUID("22222222-2222-2222-2222-222222222222")
MENSAGEM = uuid.UUID("33333333-3333-3333-3333-333333333333")
DOCUMENTO = uuid.UUID("44444444-4444-4444-4444-444444444444")

# Colunas que já existiam na 0003, por tabela. A comparação ignora as colunas novas da 0004.
LEGADO = {
    "tenants": "id, nome_empresa, nicho, plano, criado_em",
    "tenant_config": (
        "tenant_id, tom_de_voz, horario_funcionamento::text, limite_desconto_percentual, "
        "topicos_proibidos::text, confianca_minima_handoff, palavras_gatilho::text, "
        "router_confidence_threshold, min_similarity"
    ),
    "conversations": (
        "id, tenant_id, canal, contato_hash, contato_enc, status, agente_atual, "
        "ultima_atividade_em, handoff_em, iniciado_em"
    ),
    "messages": (
        "id, tenant_id, conversation_id, remetente, conteudo, tipo, external_id, intencao, "
        "intencao_confianca, status_envio, responde_a, timestamp"
    ),
    "knowledge_documents": (
        "id, tenant_id, nome_origem, content_hash, versao, num_trechos, criado_em, atualizado_em"
    ),
    "tenant_knowledge": (
        "id, tenant_id, documento_id, documento_origem, chunk_indice, chunk_texto, "
        "embedding::text, criado_em"
    ),
    "handoff_log": "id, tenant_id, conversation_id, message_id, motivo, confianca_no_momento",
    "llm_calls": "id, tenant_id, finalidade, modelo, tokens_entrada, custo_usd, sucesso",
}


async def _executar(url: str, sql: str, **params: object) -> list[tuple[object, ...]]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params)
            return [tuple(r) for r in result] if result.returns_rows else []
    finally:
        await engine.dispose()


def _sql(url: str, sql: str, **params: object) -> list[tuple[object, ...]]:
    return asyncio.run(_executar(url, sql, **params))


def _popular_empresa_legada(url: str) -> None:
    _sql(
        url,
        "INSERT INTO tenants (id, nome_empresa, nicho, plano, status) VALUES "
        "(:t, 'Clínica Sorriso (piloto)', 'clinica_odontologica', 'recepcionista', 'ativo')",
        t=PILOTO,
    )
    _sql(
        url,
        "INSERT INTO tenant_config (tenant_id, tom_de_voz, horario_funcionamento, "
        "limite_desconto_percentual, topicos_proibidos, confianca_minima_handoff, "
        "palavras_gatilho, router_confidence_threshold, min_similarity) VALUES "
        "(:t, 'Cordial.', CAST(:h AS json), 10, CAST(:p AS json), 0.7, CAST(:g AS json), 0.6, 0.3)",
        t=PILOTO,
        h='{"seg_sex": "08:00-18:00", "sabado": "08:00-12:00"}',
        p='["garantia de resultado", "diagnóstico"]',
        g='["processo", "procon"]',
    )
    _sql(
        url,
        "INSERT INTO conversations (id, tenant_id, canal, contato_hash, contato_enc, status, "
        "agente_atual) VALUES (:c, :t, 'whatsapp', 'hash', 'enc', 'aberta', 'support')",
        c=CONVERSA,
        t=PILOTO,
    )
    _sql(
        url,
        "INSERT INTO messages (id, tenant_id, conversation_id, remetente, conteudo, tipo, "
        "external_id) VALUES (:m, :t, :c, 'lead', 'Qual o horário?', 'texto', 'ext-1')",
        m=MENSAGEM,
        t=PILOTO,
        c=CONVERSA,
    )
    _sql(
        url,
        "INSERT INTO knowledge_documents (id, tenant_id, nome_origem, content_hash, num_trechos) "
        "VALUES (:d, :t, 'faq.md', 'abc', 1)",
        d=DOCUMENTO,
        t=PILOTO,
    )
    vetor = "[" + ",".join(["0.1"] * 1536) + "]"
    _sql(
        url,
        "INSERT INTO tenant_knowledge (id, tenant_id, documento_id, documento_origem, chunk_texto, "
        "embedding) VALUES (gen_random_uuid(), :t, :d, 'faq.md', 'Abrimos às 8h.', "
        "CAST(:e AS vector))",
        t=PILOTO,
        d=DOCUMENTO,
        e=vetor,
    )
    _sql(
        url,
        "INSERT INTO handoff_log (id, tenant_id, conversation_id, message_id, motivo, "
        "confianca_no_momento, resolvido_por_humano) VALUES "
        "(gen_random_uuid(), :t, :c, :m, 'palavra_gatilho:procon', 0.5, false)",
        t=PILOTO,
        c=CONVERSA,
        m=MENSAGEM,
    )
    _sql(
        url,
        "INSERT INTO llm_calls (id, tenant_id, finalidade, modelo, sucesso) VALUES "
        "(gen_random_uuid(), :t, 'roteador', 'm', true)",
        t=PILOTO,
    )


def _fotografia(url: str) -> dict[str, list[tuple[object, ...]]]:
    return {
        tabela: _sql(url, f"SELECT {colunas} FROM {tabela} ORDER BY 1")
        for tabela, colunas in LEGADO.items()
    }


def test_empresa_piloto_continua_igual_depois_da_0004() -> None:
    if os.environ.get("_BANCO_INDISPONIVEL"):
        pytest.skip("Postgres de teste indisponível")
    url = (
        make_url(_ADMIN_URL)
        .set(database="plantao_continuidade_teste")
        .render_as_string(hide_password=False)
    )
    asyncio.run(recriar_banco(url))
    cfg = alembic_config(url)

    command.upgrade(cfg, "0003")
    _popular_empresa_legada(url)
    antes = _fotografia(url)
    assert all(linhas for linhas in antes.values())  # nada ficou vazio por engano

    command.upgrade(cfg, "head")

    assert _fotografia(url) == antes
    linha = _sql(
        url,
        "SELECT slug, status, ativado_em IS NOT NULL, encerrado_em, dados_apagados_em "
        "FROM tenants WHERE id = :t",
        t=PILOTO,
    )[0]
    assert linha == ("clinica-sorriso-piloto", "ativo", True, None, None)
    novos = _sql(
        url,
        "SELECT handoff_ttl_minutos, limite_mensagens_por_minuto FROM tenant_config "
        "WHERE tenant_id = :t",
        t=PILOTO,
    )[0]
    assert novos == (60, 60)
    conversa = _sql(
        url,
        "SELECT iniciada_por, recebida_em_suspensao FROM conversations WHERE id = :c",
        c=CONVERSA,
    )[0]
    assert conversa == ("contato", False)

    # reverter e subir de novo também preserva os dados
    command.downgrade(cfg, "0003")
    assert _fotografia(url) == antes
    command.upgrade(cfg, "head")
    assert _fotografia(url) == antes
