"""Ciclo de vida: suspender e retomar uma empresa (US4, T063; FR-015 a FR-018, SC-004, research R-06).

Banco real, canal e LLM falsos. A suspensão vale para mensagens novas (webhook), para jobs já na fila (início do
job) e para respostas em andamento (checagem na gravação, protegida pela trava advisory do estado).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from apps.worker.jobs import processar_mensagem
from core.llm.ports import Finalidade
from core.tenancy.ciclo_vida import suspender
from db.admin import admin_session
from db.repositories import travar_estado_compartilhada
from db.session import tenant_session
from scripts.tenants import principal
from tests.conftest import ConexaoCriada, criar_conexao, criar_tenant
from tests.fakes.channel import FakeChannel, FakeQueue
from tests.fakes.conhecimento import inserir_conhecimento, json_roteador, json_suporte
from tests.fakes.llm import FakeLLMClient
from tests.fakes.pipeline import consultar, contexto, receber, slug_de
from tests.fakes.webhook import enviar, rodar_fila

pytestmark = pytest.mark.integration

RESPOSTA = "Aos sábados atendemos das 8h às 12h."
OPERADOR = ["--operador", "rafael"]


@dataclass
class Empresa:
    tenant_id: uuid.UUID
    conexao: ConexaoCriada
    slug: str
    llm: FakeLLMClient

    def ctx(self, canal: FakeChannel) -> dict[str, Any]:
        return contexto(self.llm, canal)


async def _empresa(db: AsyncEngine, nome: str, instancia: str, *, status: str = "ativo") -> Empresa:
    tenant_id = await criar_tenant(db, nome, status=status)
    await inserir_conhecimento(
        db, tenant_id, {"faq.md": ["Horário de atendimento: aos sábados abrimos das 8h às 12h."]}
    )
    llm = FakeLLMClient(
        {
            Finalidade.ROTEADOR: [json_roteador("suporte", 0.95)] * 40,
            Finalidade.SUPORTE: [json_suporte(RESPOSTA, 0.95)] * 40,
        }
    )
    return Empresa(
        tenant_id,
        await criar_conexao(db, tenant_id, instance_name=instancia),
        await slug_de(db, tenant_id),
        llm,
    )


async def _estado(db: AsyncEngine, tenant_id: uuid.UUID) -> str:
    return str((await consultar(db, "SELECT status FROM tenants WHERE id = :t", t=tenant_id))[0][0])


async def _suspender(tenant_id: uuid.UUID, motivo: str | None = None) -> None:
    async with admin_session() as s:
        await suspender(s, tenant_id, "rafael", motivo=motivo)


# --- comandos suspend e resume --------------------------------------------------------------------
async def test_suspend_e_resume_mudam_o_estado_e_auditam_com_operador_motivo_e_data(
    db: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    a = await _empresa(db, "Clínica A", "inst-a")

    assert await principal(["suspend", a.slug, *OPERADOR, "--motivo", "cobrança indevida"]) == 0
    assert "suspensa" in capsys.readouterr().out
    assert await _estado(db, a.tenant_id) == "suspenso"

    assert await principal(["resume", a.slug, *OPERADOR]) == 0
    assert "reativada" in capsys.readouterr().out
    assert await _estado(db, a.tenant_id) == "ativo"

    auditoria = await consultar(
        db,
        "SELECT campo, valor_anterior, valor_novo, operador, criado_em FROM audit_log "
        "WHERE entidade = 'estado' AND tenant_id = :t ORDER BY criado_em, campo DESC",
        t=a.tenant_id,
    )
    status = [(r.valor_anterior, r.valor_novo) for r in auditoria if r.campo == "status"]
    assert status == [("ativo", "suspenso"), ("suspenso", "ativo")]
    motivos = [r.valor_novo for r in auditoria if r.campo == "motivo"]
    assert motivos == ["cobrança indevida"]
    assert all(r.operador == "rafael" and r.criado_em is not None for r in auditoria)


@pytest.mark.parametrize(
    ("estado", "comando", "mensagem"),
    [
        ("em_configuracao", "suspend", "Transicao invalida: em_configuracao -> suspenso"),
        ("suspenso", "suspend", "Transicao invalida: suspenso -> suspenso"),
        ("encerrado", "suspend", "Transicao invalida: encerrado -> suspenso"),
        ("ativo", "resume", "Transicao invalida: ativo -> ativo"),
        ("em_configuracao", "resume", "Transicao invalida: em_configuracao -> ativo"),
        ("encerrado", "resume", "Transicao invalida: encerrado -> ativo"),
    ],
)
async def test_transicoes_invalidas_sao_recusadas_sem_alterar_nada(
    db: AsyncEngine,
    capsys: pytest.CaptureFixture[str],
    estado: str,
    comando: str,
    mensagem: str,
) -> None:
    tenant_id = await criar_tenant(db, "Clínica X", status=estado)
    slug = await slug_de(db, tenant_id)

    assert await principal([comando, slug, *OPERADOR]) == 1

    assert mensagem in capsys.readouterr().err
    assert await _estado(db, tenant_id) == estado
    assert await consultar(db, "SELECT 1 FROM audit_log") == []


async def test_suspend_e_resume_exigem_operador_e_empresa_existente(
    db: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await principal(["suspend", "qualquer"]) == 2
    assert "--operador" in capsys.readouterr().err
    assert await principal(["resume", "nao-existe", *OPERADOR]) == 1
    assert "nao encontrada" in capsys.readouterr().err


# --- mensagens já na fila e respostas em andamento ---------------------------------------------------
async def test_mensagem_enfileirada_antes_da_suspensao_devolve_empresa_inativa_e_nao_envia(
    db: AsyncEngine,
) -> None:
    a = await _empresa(db, "Clínica A", "inst-a")
    mid, _ = await receber(a.tenant_id)
    await _suspender(a.tenant_id)
    canal = FakeChannel()

    resultado = await processar_mensagem(a.ctx(canal), str(a.tenant_id), str(mid), "c-1")

    assert resultado == "empresa_inativa"
    assert a.llm.chamadas == [] and a.llm.embeds == [] and canal.envios == []
    assert await consultar(db, "SELECT 1 FROM messages WHERE responde_a IS NOT NULL") == []


async def test_estado_que_muda_durante_o_grafo_impede_gravar_e_enviar(db: AsyncEngine) -> None:
    a = await _empresa(db, "Clínica A", "inst-a")
    mid, _ = await receber(a.tenant_id)
    canal = FakeChannel()
    grafo = contexto(a.llm, canal)["grafo"]

    class GrafoQueSuspende:
        """Suspende a empresa depois de decidir e antes de gravar, como um operador no meio do job."""

        async def executar(self, entrada: Any, config: Any) -> Any:
            decisao = await grafo.executar(entrada, config)
            await _suspender(a.tenant_id)
            return decisao

    resultado = await processar_mensagem(
        {"grafo": GrafoQueSuspende(), "channel": canal}, str(a.tenant_id), str(mid), "c-1"
    )

    assert resultado == "empresa_inativa"
    assert canal.envios == []
    assert await consultar(db, "SELECT 1 FROM messages WHERE responde_a IS NOT NULL") == []
    assert await consultar(db, "SELECT 1 FROM handoff_log") == []
    assert await _estado(db, a.tenant_id) == "suspenso"


async def test_mudanca_de_estado_espera_quem_ja_estava_gravando(db: AsyncEngine) -> None:
    a = await _empresa(db, "Clínica A", "inst-a")
    async with tenant_session(a.tenant_id) as s:
        await travar_estado_compartilhada(s, a.tenant_id)  # um job no meio da gravação
        suspensao = asyncio.create_task(_suspender(a.tenant_id))
        concluidas, _ = await asyncio.wait({suspensao}, timeout=0.7)
        assert not concluidas, "a suspensão não esperou a gravação em andamento"
        assert await _estado(db, a.tenant_id) == "ativo"
    await asyncio.wait_for(suspensao, timeout=10)  # a gravação terminou: a trava foi liberada
    assert await _estado(db, a.tenant_id) == "suspenso"


# --- mensagens recebidas durante a suspensão ---------------------------------------------------------
async def test_mensagem_recebida_suspensa_fica_guardada_sem_job_e_a_reativacao_nao_a_reprocessa(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine
) -> None:
    a = await _empresa(db, "Clínica A", "inst-a")
    canal = FakeChannel()
    ctxs = {a.tenant_id: a.ctx(canal)}

    assert await principal(["suspend", a.slug, *OPERADOR]) == 0
    assert await enviar(cliente, a.conexao, "S1", "Mensagem durante a suspensão") == "suspended"
    assert fila.jobs == []
    guardadas = await consultar(
        db,
        "SELECT m.conteudo, c.recebida_em_suspensao FROM messages m "
        "JOIN conversations c ON c.id = m.conversation_id",
    )
    assert [(g.conteudo, g.recebida_em_suspensao) for g in guardadas] == [
        ("Mensagem durante a suspensão", True)
    ]

    assert await principal(["resume", a.slug, *OPERADOR]) == 0
    assert fila.jobs == [] and await rodar_fila(fila, ctxs) == []  # o backlog não volta
    assert canal.envios == [] and a.llm.chamadas == []

    assert await enviar(cliente, a.conexao, "S2") == "queued"
    resultados = await rodar_fila(fila, ctxs)
    assert [r for _, r, _ in resultados] == ["respondida"]
    assert [e[2] for e in canal.envios] == [RESPOSTA]
    historico = await consultar(db, "SELECT conteudo FROM messages ORDER BY timestamp")
    assert historico[0].conteudo == "Mensagem durante a suspensão"  # preservado no histórico


# --- SC-004: a suspensão de A não atrapalha B ---------------------------------------------------------
async def test_b_mantem_a_meta_de_10_segundos_enquanto_a_esta_suspensa(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine
) -> None:
    a = await _empresa(db, "Clínica A", "inst-a")
    b = await _empresa(db, "Clínica B", "inst-b")
    canal = FakeChannel()
    ctxs = {a.tenant_id: a.ctx(canal), b.tenant_id: b.ctx(canal)}
    await enviar(cliente, a.conexao, "A-na-fila")  # já enfileirada quando A for suspensa
    await _suspender(a.tenant_id, "incidente")

    assert await enviar(cliente, a.conexao, "A-nova") == "suspended"
    estados_b = [await enviar(cliente, b.conexao, f"B{i}") for i in range(10)]
    assert estados_b == ["queued"] * 10

    resultados = await rodar_fila(fila, ctxs)
    de_a = [r for t, r, _ in resultados if t == a.tenant_id]
    de_b = [(r, seg) for t, r, seg in resultados if t == b.tenant_id]
    assert de_a == ["empresa_inativa"]
    assert len(de_b) == 10 and all(r == "respondida" for r, _ in de_b)
    assert sum(seg <= 10.0 for _, seg in de_b) / len(de_b) >= 0.9
    assert {i for i, _, _ in canal.envios} == {"inst-b"}
