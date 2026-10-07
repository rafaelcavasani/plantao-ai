"""Privilégios do papel `plantao_painel` (spec 004, T010; ADR-0006, FR-004, FR-005).

O painel nunca pode ler texto de mensagem, contato nem credenciais: isso é uma propriedade do banco, não da
disciplina do código.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from db.painel import painel_session

pytestmark = pytest.mark.integration

PAPEL = "plantao_painel"

# (tabela, coluna) que o painel NUNCA pode ler.
PROIBIDAS = [
    ("messages", "conteudo"),
    ("messages", "external_id"),
    ("messages", "intencoes_secundarias"),
    ("conversations", "contato_hash"),
    ("conversations", "contato_enc"),
    ("tenant_knowledge", "chunk_texto"),
    ("tenant_knowledge", "embedding"),
    ("channel_credentials", "webhook_secret_hash"),
    ("channel_credentials", "api_key_enc"),
    ("channel_credentials", "connection_id"),
    ("leads", "telefone"),
    ("leads", "nome"),
    ("llm_calls", "custo_usd"),
]

# (tabela, coluna) que o painel precisa ler.
PERMITIDAS = [
    ("messages", "remetente"),
    ("messages", "tipo"),
    ("messages", "timestamp"),
    ("messages", "intencao"),
    ("messages", "status_envio"),
    ("conversations", "status"),
    ("conversations", "iniciado_em"),
    ("conversations", "ultima_atividade_em"),
    ("knowledge_documents", "nome_origem"),
    ("knowledge_documents", "num_trechos"),
    ("channel_connections", "instance_name"),
    ("channel_connections", "verificada_em"),
    ("tenants", "versao"),
    ("tenants", "nome_empresa"),
    ("tenant_config", "tom_de_voz"),
    ("audit_log", "valor_novo"),
    ("readiness_checks", "aprovado"),
    ("handoff_log", "motivo"),
    ("painel_agregado_hora", "custo_usd"),
    ("painel_situacao", "ultima_mensagem_em"),
]

TABELAS_DE_NEGOCIO = [
    "tenants",
    "tenant_config",
    "messages",
    "conversations",
    "knowledge_documents",
    "tenant_knowledge",
    "channel_connections",
    "channel_credentials",
    "readiness_checks",
    "audit_log",
    "handoff_log",
    "llm_calls",
    "leads",
    "appointments",
    "billing_events",
    "usage_metrics",
    "painel_agregado_hora",
    "painel_situacao",
]


async def _tem(engine: AsyncEngine, tabela: str, coluna: str) -> bool:
    async with engine.connect() as conn:
        return bool(
            (
                await conn.execute(
                    text("SELECT has_column_privilege(:papel, :tabela, :coluna, 'SELECT')"),
                    {"papel": PAPEL, "tabela": tabela, "coluna": coluna},
                )
            ).scalar_one()
        )


@pytest.mark.parametrize(("tabela", "coluna"), PROIBIDAS)
async def test_painel_nao_le_coluna_sensivel(
    admin_engine: AsyncEngine, tabela: str, coluna: str
) -> None:
    assert not await _tem(admin_engine, tabela, coluna), f"{PAPEL} lê {tabela}.{coluna}"


@pytest.mark.parametrize(("tabela", "coluna"), PERMITIDAS)
async def test_painel_le_coluna_liberada(
    admin_engine: AsyncEngine, tabela: str, coluna: str
) -> None:
    assert await _tem(admin_engine, tabela, coluna), f"{PAPEL} não lê {tabela}.{coluna}"


@pytest.mark.parametrize("tabela", TABELAS_DE_NEGOCIO)
async def test_painel_nao_escreve_em_nenhuma_tabela(admin_engine: AsyncEngine, tabela: str) -> None:
    async with admin_engine.connect() as conn:
        for acao in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            tem = (
                await conn.execute(
                    text("SELECT has_table_privilege(:papel, :tabela, :acao)"),
                    {"papel": PAPEL, "tabela": tabela, "acao": acao},
                )
            ).scalar_one()
            assert not tem, f"{PAPEL} tem {acao} em {tabela}"


async def test_papel_nao_e_superusuario_nem_ignora_rls(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        linha = (
            await conn.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles "
                    "WHERE rolname = :p"
                ),
                {"p": PAPEL},
            )
        ).one()
    assert tuple(linha) == (False, False, False, False)


async def test_consulta_ao_conteudo_falha_com_permissao_negada(db: AsyncEngine) -> None:
    async with painel_session() as s:
        with pytest.raises(DBAPIError, match="permission denied"):
            await s.execute(text("SELECT conteudo FROM messages LIMIT 1"))


async def test_select_estrela_em_conversas_tambem_e_negado(db: AsyncEngine) -> None:
    async with painel_session() as s:
        with pytest.raises(DBAPIError, match="permission denied"):
            await s.execute(text("SELECT * FROM conversations LIMIT 1"))


async def test_credenciais_sao_inacessiveis(db: AsyncEngine) -> None:
    async with painel_session() as s:
        with pytest.raises(DBAPIError, match="permission denied"):
            await s.execute(text("SELECT count(*) FROM channel_credentials"))
