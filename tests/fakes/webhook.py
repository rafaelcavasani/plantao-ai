"""Auxiliares dos testes que passam pelo webhook e pelo worker (fila falsa, canal falso)."""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from apps.worker.jobs import processar_mensagem
from tests.conftest import ConexaoCriada
from tests.fakes.channel import FakeQueue
from tests.fakes.pipeline import JID

URL = "/webhooks/whatsapp"
PERGUNTA = "Qual o horário de atendimento aos sábados?"


async def enviar(
    cliente: httpx.AsyncClient,
    conexao: ConexaoCriada,
    id: str = "ID-1",
    texto: str = PERGUNTA,
    jid: str = JID,
) -> str:
    """Entrega uma mensagem pelo webhook da empresa dona da conexão. Devolve o `status` da resposta."""
    corpo = {
        "event": "messages.upsert",
        "instance": conexao.instance_name,
        "data": {
            "key": {"remoteJid": jid, "fromMe": False, "id": id},
            "message": {"conversation": texto},
        },
    }
    r = await cliente.post(URL, json=corpo, headers={"X-Webhook-Token": conexao.webhook_secret})
    assert r.status_code == 200
    return str(r.json()["status"])


async def rodar_fila(
    fila: FakeQueue, ctxs: dict[uuid.UUID, dict[str, Any]]
) -> list[tuple[uuid.UUID, str, float]]:
    """Executa os jobs enfileirados. Devolve (empresa, resultado, segundos) de cada um."""
    jobs, fila.jobs[:] = list(fila.jobs), []
    saida: list[tuple[uuid.UUID, str, float]] = []
    for _, (tenant, mensagem, correlacao), _kw in jobs:
        inicio = time.perf_counter()
        resultado = await processar_mensagem(ctxs[uuid.UUID(tenant)], tenant, mensagem, correlacao)
        saida.append((uuid.UUID(tenant), resultado, time.perf_counter() - inicio))
    return saida
