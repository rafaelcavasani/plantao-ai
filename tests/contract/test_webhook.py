"""Contrato do webhook `POST /webhooks/whatsapp` por conexão (T021, T064).

Usa banco real, Redis falso e fila falsa. A empresa vem da instância do corpo; o token é o da conexão.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from apps.api.deps import get_queue, get_redis
from apps.api.main import app
from core.config import settings
from tests.conftest import ConexaoCriada, criar_conexao, criar_tenant
from tests.fakes.channel import FakeQueue

URL = "/webhooks/whatsapp"
JID = "5511999990000@s.whatsapp.net"


@dataclass(frozen=True)
class Empresa:
    tenant_id: uuid.UUID
    conexao: ConexaoCriada

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Webhook-Token": self.conexao.webhook_secret}


def payload(
    texto: str | None = "Que horas vocês abrem no sábado?",
    id: str = "3EB0A1",
    jid: str = JID,
    instance: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    key: dict[str, Any] = {"remoteJid": jid, "fromMe": False, "id": id}
    key.update(extra)
    mensagem = {"conversation": texto} if texto is not None else {"audioMessage": {"url": "x"}}
    corpo: dict[str, Any] = {"event": "messages.upsert", "data": {"key": key, "message": mensagem}}
    if instance is not None:
        corpo["instance"] = instance
    return corpo


async def _empresa(db: AsyncEngine, nome: str, **config: object) -> Empresa:
    tenant_id = await criar_tenant(db, nome, **config)
    return Empresa(tenant_id, await criar_conexao(db, tenant_id))


@pytest.fixture
def fila() -> FakeQueue:
    return FakeQueue()


@pytest_asyncio.fixture
async def cliente(fila: FakeQueue, db: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    redis = FakeAsyncRedis()
    app.dependency_overrides[get_queue] = lambda: fila
    app.dependency_overrides[get_redis] = lambda: redis
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    await redis.aclose()


@pytest_asyncio.fixture
async def a(db: AsyncEngine) -> Empresa:
    return await _empresa(db, "Clínica A")


@pytest_asyncio.fixture
async def b(db: AsyncEngine) -> Empresa:
    return await _empresa(db, "Clínica B")


async def _contagem(db: AsyncEngine, tabela: str, tenant_id: uuid.UUID | None = None) -> int:
    filtro = f" WHERE tenant_id = '{tenant_id}'" if tenant_id else ""
    async with db.connect() as conn:
        return int(
            (await conn.execute(text(f"SELECT count(*) FROM {tabela}{filtro}"))).scalar_one()
        )


async def _enviar(
    cliente: httpx.AsyncClient, empresa: Empresa, corpo: dict[str, Any] | None = None, **kw: Any
) -> httpx.Response:
    corpo = corpo if corpo is not None else payload(**kw)
    corpo.setdefault("instance", empresa.conexao.instance_name)
    return await cliente.post(URL, json=corpo, headers=empresa.headers)


# --- autenticação ---------------------------------------------------------------------------
@pytest.mark.parametrize("headers", [{}, {"X-Webhook-Token": "errado"}, {"X-Webhook-Token": ""}])
async def test_token_ausente_ou_invalido_da_401(
    cliente: httpx.AsyncClient,
    fila: FakeQueue,
    db: AsyncEngine,
    a: Empresa,
    headers: dict[str, str],
) -> None:
    r = await cliente.post(URL, json=payload(instance=a.conexao.instance_name), headers=headers)
    assert r.status_code == 401 and r.json() == {"detail": "invalid token"}
    assert fila.jobs == [] and await _contagem(db, "messages") == 0


async def test_token_de_a_com_instancia_de_b_da_401_e_nada_e_gravado_em_b(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, a: Empresa, b: Empresa
) -> None:
    r = await cliente.post(URL, json=payload(instance=b.conexao.instance_name), headers=a.headers)
    assert r.status_code == 401
    assert fila.jobs == []
    for tabela in ("messages", "conversations"):
        assert await _contagem(db, tabela, b.tenant_id) == 0
        assert await _contagem(db, tabela, a.tenant_id) == 0


async def test_instancia_desconhecida_e_token_errado_sao_indistinguiveis(
    cliente: httpx.AsyncClient, a: Empresa
) -> None:
    desconhecida = await cliente.post(URL, json=payload(instance="nao-existe"), headers=a.headers)
    token_errado = await cliente.post(
        URL,
        json=payload(instance=a.conexao.instance_name),
        headers={"X-Webhook-Token": "errado"},
    )
    assert desconhecida.status_code == token_errado.status_code == 401
    assert desconhecida.content == token_errado.content
    assert desconhecida.headers.get("content-type") == token_errado.headers.get("content-type")


@pytest.mark.parametrize("instance", [None, "", 123, ["x"], {"a": 1}])
async def test_sem_instancia_ou_de_tipo_errado_da_401(
    cliente: httpx.AsyncClient, fila: FakeQueue, a: Empresa, instance: object
) -> None:
    corpo = payload()
    if instance is not None:
        corpo["instance"] = instance
    r = await cliente.post(URL, json=corpo, headers=a.headers)
    assert r.status_code == 401 and r.json() == {"detail": "invalid token"}
    assert fila.jobs == []


async def test_segredo_global_antigo_nao_autentica_mais(
    cliente: httpx.AsyncClient, a: Empresa
) -> None:
    r = await cliente.post(
        URL,
        json=payload(instance=a.conexao.instance_name),
        headers={"X-Webhook-Token": "segredo-de-teste"},
    )
    assert r.status_code == 401


@pytest.mark.parametrize("corpo", ["não é json", "[1, 2]", '"texto"', "null"])
async def test_corpo_que_nao_e_objeto_json_da_422(
    cliente: httpx.AsyncClient, a: Empresa, corpo: str
) -> None:
    r = await cliente.post(
        URL, content=corpo, headers={**a.headers, "Content-Type": "application/json"}
    )
    assert r.status_code == 422


# --- fluxo principal ------------------------------------------------------------------------
async def test_mensagem_nova_e_persistida_e_enfileirada(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, a: Empresa
) -> None:
    r = await _enviar(cliente, a)
    assert r.status_code == 200 and r.json() == {"status": "queued"}
    assert len(fila.jobs) == 1
    funcao, args, kwargs = fila.jobs[0]
    assert funcao == "processar_mensagem" and args[0] == str(a.tenant_id)
    assert kwargs["_job_id"] == f"{a.tenant_id}:{args[1]}"
    async with db.connect() as conn:
        linha = (
            await conn.execute(
                text("SELECT id, remetente, conteudo, tipo, external_id FROM messages")
            )
        ).one()
    assert str(linha.id) == args[1] and linha.remetente == "lead" and linha.tipo == "texto"
    assert linha.conteudo == "Que horas vocês abrem no sábado?" and linha.external_id == "3EB0A1"


async def test_telefone_nunca_vai_para_fila_nem_para_o_banco_em_claro(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, a: Empresa
) -> None:
    await _enviar(cliente, a)
    assert "5511999990000" not in repr(fila.jobs)
    async with db.connect() as conn:
        linha = (
            await conn.execute(text("SELECT contato_hash, contato_enc FROM conversations"))
        ).one()
        todas = " ".join(str(v) for v in (await conn.execute(text("SELECT * FROM messages"))).one())
    assert "5511999990000" not in f"{linha.contato_hash} {linha.contato_enc} {todas}"


async def test_duplicata_devolve_duplicate_sem_enfileirar(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, a: Empresa
) -> None:
    primeira = await _enviar(cliente, a)
    segunda = await _enviar(cliente, a)
    assert primeira.json() == {"status": "queued"} and segunda.json() == {"status": "duplicate"}
    assert len(fila.jobs) == 1 and await _contagem(db, "messages") == 1


async def test_mesmo_external_id_em_duas_empresas_e_enfileirado_nas_duas(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, a: Empresa, b: Empresa
) -> None:
    ra = await _enviar(cliente, a, id="MESMO")
    rb = await _enviar(cliente, b, id="MESMO")
    assert ra.json() == rb.json() == {"status": "queued"}
    assert sorted(job[1][0] for job in fila.jobs) == sorted([str(a.tenant_id), str(b.tenant_id)])
    assert await _contagem(db, "messages", a.tenant_id) == 1
    assert await _contagem(db, "messages", b.tenant_id) == 1
    # a mesma empresa repetindo continua sendo duplicata
    assert (await _enviar(cliente, a, id="MESMO")).json() == {"status": "duplicate"}


async def test_mesmo_telefone_em_duas_empresas_gera_conversas_separadas(
    cliente: httpx.AsyncClient, db: AsyncEngine, a: Empresa, b: Empresa
) -> None:
    await _enviar(cliente, a, id="A1")
    await _enviar(cliente, b, id="B1")
    assert await _contagem(db, "conversations", a.tenant_id) == 1
    assert await _contagem(db, "conversations", b.tenant_id) == 1


async def test_mesmo_contato_reaproveita_a_conversa(
    cliente: httpx.AsyncClient, db: AsyncEngine, a: Empresa
) -> None:
    await _enviar(cliente, a, id="A")
    await _enviar(cliente, a, id="B", texto="Outra pergunta")
    assert await _contagem(db, "conversations") == 1 and await _contagem(db, "messages") == 2


async def test_contatos_diferentes_geram_conversas_diferentes(
    cliente: httpx.AsyncClient, db: AsyncEngine, a: Empresa
) -> None:
    await _enviar(cliente, a, id="A")
    await _enviar(cliente, a, id="B", jid="5511888880000@s.whatsapp.net")
    assert await _contagem(db, "conversations") == 2


async def test_audio_vira_nao_texto_e_e_enfileirado(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, a: Empresa
) -> None:
    r = await _enviar(cliente, a, texto=None)
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
    cliente: httpx.AsyncClient,
    fila: FakeQueue,
    db: AsyncEngine,
    a: Empresa,
    corpo: dict[str, Any],
) -> None:
    r = await _enviar(cliente, a, dict(corpo))
    assert r.status_code == 200 and r.json() == {"status": "ignored"}
    assert fila.jobs == [] and await _contagem(db, "messages") == 0


# --- estado da empresa ----------------------------------------------------------------------
@pytest.mark.parametrize("estado", ["em_configuracao", "encerrado"])
async def test_empresa_em_configuracao_ou_encerrada_ignora_sem_gravar(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, estado: str
) -> None:
    empresa = await _empresa(db, "Fora do ar")
    async with db.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET status = :s WHERE id = :i"),
            {"s": estado, "i": empresa.tenant_id},
        )
    r = await _enviar(cliente, empresa)
    assert r.status_code == 200 and r.json() == {"status": "ignored"}
    assert fila.jobs == []
    assert await _contagem(db, "messages") == 0 and await _contagem(db, "conversations") == 0


async def test_empresa_suspensa_guarda_a_mensagem_marcada_e_nao_enfileira(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, a: Empresa
) -> None:
    async with db.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET status = 'suspenso' WHERE id = :i"), {"i": a.tenant_id}
        )
    r = await _enviar(cliente, a)
    assert r.status_code == 200 and r.json() == {"status": "suspended"}
    assert fila.jobs == []
    assert await _contagem(db, "messages") == 1
    async with db.connect() as conn:
        marca = (
            await conn.execute(text("SELECT recebida_em_suspensao FROM conversations"))
        ).scalar_one()
    assert marca is True


async def test_suspensa_repetida_continua_duplicata(
    cliente: httpx.AsyncClient, db: AsyncEngine, a: Empresa
) -> None:
    async with db.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET status = 'suspenso' WHERE id = :i"), {"i": a.tenant_id}
        )
    assert (await _enviar(cliente, a, id="X")).json() == {"status": "suspended"}
    assert (await _enviar(cliente, a, id="X")).json() == {"status": "duplicate"}


async def test_estado_e_lido_do_banco_a_cada_mensagem(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, a: Empresa
) -> None:
    assert (await _enviar(cliente, a, id="1")).json() == {"status": "queued"}
    async with db.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET status = 'suspenso' WHERE id = :i"), {"i": a.tenant_id}
        )
    assert (await _enviar(cliente, a, id="2")).json() == {"status": "suspended"}
    async with db.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET status = 'ativo' WHERE id = :i"), {"i": a.tenant_id}
        )
    assert (await _enviar(cliente, a, id="3")).json() == {"status": "queued"}
    assert len(fila.jobs) == 2


async def test_suspender_a_nao_afeta_b(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, a: Empresa, b: Empresa
) -> None:
    async with db.begin() as conn:
        await conn.execute(
            text("UPDATE tenants SET status = 'suspenso' WHERE id = :i"), {"i": a.tenant_id}
        )
    assert (await _enviar(cliente, a, id="A")).json() == {"status": "suspended"}
    assert (await _enviar(cliente, b, id="B")).json() == {"status": "queued"}
    assert [job[1][0] for job in fila.jobs] == [str(b.tenant_id)]


# --- limite por empresa ---------------------------------------------------------------------
async def test_limite_por_minuto_vem_da_configuracao_da_empresa(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine
) -> None:
    empresa = await _empresa(db, "Limite 2", limite_mensagens_por_minuto=2)
    estados = [(await _enviar(cliente, empresa, id=f"M{i}")).json()["status"] for i in range(4)]
    assert estados == ["queued", "queued", "rate_limited", "rate_limited"]
    assert len(fila.jobs) == 2 and await _contagem(db, "messages") == 2


async def test_limite_excedido_em_a_nao_afeta_b(
    cliente: httpx.AsyncClient, fila: FakeQueue, db: AsyncEngine, b: Empresa
) -> None:
    a = await _empresa(db, "Limite 1", limite_mensagens_por_minuto=1)
    assert (await _enviar(cliente, a, id="A1")).json()["status"] == "queued"
    assert (await _enviar(cliente, a, id="A2")).json()["status"] == "rate_limited"
    for i in range(5):
        assert (await _enviar(cliente, b, id=f"B{i}")).json()["status"] == "queued"


async def test_resposta_rapida_e_sem_llm(cliente: httpx.AsyncClient, a: Empresa) -> None:
    import time

    inicio = time.perf_counter()
    r = await _enviar(cliente, a)
    assert r.status_code == 200 and time.perf_counter() - inicio < 0.5


# --- logs -----------------------------------------------------------------------------------
async def test_logs_nao_contem_payload_telefone_token_nem_chave(
    cliente: httpx.AsyncClient, caplog: pytest.LogCaptureFixture, a: Empresa
) -> None:
    with caplog.at_level(logging.DEBUG):
        await _enviar(cliente, a, texto="segredo-do-cliente")
        await cliente.post(
            URL,
            json=payload(instance=a.conexao.instance_name),
            headers={"X-Webhook-Token": "tk-errado"},
        )
        await cliente.post(URL, json=payload(instance="desconhecida"), headers=a.headers)
    texto = caplog.text + " ".join(
        str(r.__dict__) for r in caplog.records if r.name.startswith("plantao")
    )
    for proibido in (
        "5511999990000",
        "segredo-do-cliente",
        a.conexao.webhook_secret,
        a.conexao.api_key,
        "tk-errado",
    ):
        assert proibido not in texto


async def test_instancia_desconhecida_e_registrada_truncada_e_sanitizada(
    cliente: httpx.AsyncClient, caplog: pytest.LogCaptureFixture, a: Empresa
) -> None:
    ataque = "x" * 200 + "\nlinha-forjada<script>"
    with caplog.at_level(logging.WARNING):
        r = await cliente.post(URL, json=payload(instance=ataque), headers=a.headers)
    assert r.status_code == 401
    registro = [r for r in caplog.records if r.getMessage() == "conexao_desconhecida"]
    assert len(registro) == 1
    instance = registro[0].dados["instance"]  # type: ignore[attr-defined]
    assert len(instance) == 64 and "\n" not in instance and "<" not in instance


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
