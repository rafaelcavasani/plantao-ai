"""Contrato do webhook `POST /webhooks/whatsapp` (T035). Usa banco real, Redis falso e fila falsa."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from apps.api.deps import get_queue, get_redis, get_tenant_id
from apps.api.main import app
from core.config import settings
from tests.fakes.channel import FakeQueue

URL = "/webhooks/whatsapp"
JID = "5511999990000@s.whatsapp.net"
TOKEN = {"X-Webhook-Token": "segredo-de-teste"}


def payload(
    texto: str | None = "Que horas vocês abrem no sábado?",
    id: str = "3EB0A1",
    jid: str = JID,
    **extra: Any,
) -> dict[str, Any]:
    key: dict[str, Any] = {"remoteJid": jid, "fromMe": False, "id": id}
    key.update(extra)
    mensagem = {"conversation": texto} if texto is not None else {"audioMessage": {"url": "x"}}
    return {"event": "messages.upsert", "data": {"key": key, "message": mensagem}}


@pytest.fixture
def fila() -> FakeQueue:
    return FakeQueue()


@pytest_asyncio.fixture
async def cliente(tenant_a: uuid.UUID, fila: FakeQueue) -> AsyncIterator[httpx.AsyncClient]:
    redis = FakeAsyncRedis()
    app.dependency_overrides[get_tenant_id] = lambda: tenant_a
    app.dependency_overrides[get_queue] = lambda: fila
    app.dependency_overrides[get_redis] = lambda: redis
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    await redis.aclose()


async def _contagem(db: AsyncEngine, tabela: str) -> int:
    async with db.connect() as conn:
        return int((await conn.execute(text(f"SELECT count(*) FROM {tabela}"))).scalar_one())


# --- autenticação ---------------------------------------------------------------------------
@pytest.mark.parametrize("headers", [{}, {"X-Webhook-Token": "errado"}, {"X-Webhook-Token": ""}])
async def test_token_ausente_ou_invalido_da_401(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, headers: dict[str, str]
) -> None:
    r = await cliente.post(URL, json=payload(), headers=headers)
    assert r.status_code == 401 and r.json() == {"detail": "invalid token"}
    assert fila.jobs == [] and await _contagem(db, "messages") == 0


async def test_segredo_nao_configurado_rejeita_tudo(
    cliente: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "whatsapp_webhook_secret", "")
    r = await cliente.post(URL, json=payload(), headers={"X-Webhook-Token": ""})
    assert r.status_code == 401


@pytest.mark.parametrize("corpo", ["não é json", "[1, 2]", '"texto"', "null"])
async def test_corpo_que_nao_e_objeto_json_da_422(cliente: httpx.AsyncClient, corpo: str) -> None:
    r = await cliente.post(
        URL, content=corpo, headers={**TOKEN, "Content-Type": "application/json"}
    )
    assert r.status_code == 422


# --- fluxo principal ------------------------------------------------------------------------
async def test_mensagem_nova_e_persistida_e_enfileirada(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    r = await cliente.post(URL, json=payload(), headers=TOKEN)
    assert r.status_code == 200 and r.json() == {"status": "queued"}
    assert len(fila.jobs) == 1
    funcao, args, kwargs = fila.jobs[0]
    assert funcao == "processar_mensagem" and args[0] == str(tenant_a)
    assert kwargs["_job_id"] == args[1]  # job_id = message_id, idempotente na fila
    async with db.connect() as conn:
        linha = (
            await conn.execute(
                text("SELECT id, remetente, conteudo, tipo, external_id FROM messages")
            )
        ).one()
    assert str(linha.id) == args[1] and linha.remetente == "lead" and linha.tipo == "texto"
    assert linha.conteudo == "Que horas vocês abrem no sábado?" and linha.external_id == "3EB0A1"


async def test_telefone_nunca_vai_para_fila_nem_para_o_banco_em_claro(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine
) -> None:
    await cliente.post(URL, json=payload(), headers=TOKEN)
    assert "5511999990000" not in repr(fila.jobs)
    async with db.connect() as conn:
        linha = (
            await conn.execute(text("SELECT contato_hash, contato_enc FROM conversations"))
        ).one()
        todas = " ".join(str(v) for v in (await conn.execute(text("SELECT * FROM messages"))).one())
    assert "5511999990000" not in f"{linha.contato_hash} {linha.contato_enc} {todas}"


async def test_duplicata_devolve_duplicate_sem_enfileirar(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine
) -> None:
    primeira = await cliente.post(URL, json=payload(), headers=TOKEN)
    segunda = await cliente.post(URL, json=payload(), headers=TOKEN)
    assert primeira.json() == {"status": "queued"} and segunda.json() == {"status": "duplicate"}
    assert len(fila.jobs) == 1 and await _contagem(db, "messages") == 1


async def test_mesmo_contato_reaproveita_a_conversa(
    cliente: httpx.AsyncClient, db: AsyncEngine
) -> None:
    await cliente.post(URL, json=payload(id="A"), headers=TOKEN)
    await cliente.post(URL, json=payload("Outra pergunta", id="B"), headers=TOKEN)
    assert await _contagem(db, "conversations") == 1 and await _contagem(db, "messages") == 2


async def test_contatos_diferentes_geram_conversas_diferentes(
    cliente: httpx.AsyncClient, db: AsyncEngine
) -> None:
    await cliente.post(URL, json=payload(id="A"), headers=TOKEN)
    await cliente.post(URL, json=payload(id="B", jid="5511888880000@s.whatsapp.net"), headers=TOKEN)
    assert await _contagem(db, "conversations") == 2


async def test_audio_vira_nao_texto_e_e_enfileirado(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine
) -> None:
    r = await cliente.post(URL, json=payload(None), headers=TOKEN)
    assert r.json() == {"status": "queued"} and len(fila.jobs) == 1
    async with db.connect() as conn:
        linha = (await conn.execute(text("SELECT tipo, conteudo FROM messages"))).one()
    assert (linha.tipo, linha.conteudo) == ("nao_texto", "")


@pytest.mark.parametrize(
    "corpo",
    [
        payload(fromMe=True),
        payload(jid="123@g.us"),
        {"event": "connection.update", "data": {"state": "open"}},
        {
            "event": "messages.upsert",
            "data": {"key": {"remoteJid": JID, "fromMe": False}, "message": {"conversation": "oi"}},
        },
    ],
)
async def test_eventos_ignorados(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, corpo: dict[str, Any]
) -> None:
    r = await cliente.post(URL, json=corpo, headers=TOKEN)
    assert r.status_code == 200 and r.json() == {"status": "ignored"}
    assert fila.jobs == [] and await _contagem(db, "messages") == 0


async def test_limite_por_minuto(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_msgs_per_min", 2)
    estados = [
        (await cliente.post(URL, json=payload(id=f"M{i}"), headers=TOKEN)).json()["status"]
        for i in range(4)
    ]
    assert estados == ["queued", "queued", "rate_limited", "rate_limited"]
    assert len(fila.jobs) == 2 and await _contagem(db, "messages") == 2


async def test_limite_e_por_tenant(
    cliente: httpx.AsyncClient,
    fila: FakeQueue,
    tenant_b: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rate_limit_msgs_per_min", 1)
    assert (await cliente.post(URL, json=payload(id="A"), headers=TOKEN)).json()[
        "status"
    ] == "queued"
    assert (await cliente.post(URL, json=payload(id="B"), headers=TOKEN)).json()[
        "status"
    ] == "rate_limited"
    app.dependency_overrides[get_tenant_id] = lambda: tenant_b
    assert (await cliente.post(URL, json=payload(id="C"), headers=TOKEN)).json()[
        "status"
    ] == "queued"


async def test_resposta_rapida_e_sem_llm(cliente: httpx.AsyncClient) -> None:
    import time

    inicio = time.perf_counter()
    r = await cliente.post(URL, json=payload(), headers=TOKEN)
    assert r.status_code == 200 and time.perf_counter() - inicio < 0.5


async def test_logs_nao_contem_payload_nem_telefone(
    cliente: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        await cliente.post(URL, json=payload("segredo-do-cliente"), headers=TOKEN)
    texto = caplog.text + " ".join(
        str(r.__dict__) for r in caplog.records if r.name.startswith("plantao")
    )
    assert "5511999990000" not in texto and "segredo-do-cliente" not in texto


# --- GET de verificação ---------------------------------------------------------------------
async def test_verificacao_da_meta_aceita_token_correto(cliente: httpx.AsyncClient) -> None:
    r = await cliente.get(
        URL,
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "42",
            "hub.verify_token": settings.whatsapp_verify_token,
        },
    )
    assert r.status_code == 200 and r.text == "42"


async def test_verificacao_da_meta_rejeita_token_errado(cliente: httpx.AsyncClient) -> None:
    r = await cliente.get(
        URL, params={"hub.mode": "subscribe", "hub.challenge": "42", "hub.verify_token": "x"}
    )
    assert r.status_code == 403
