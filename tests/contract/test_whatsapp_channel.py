"""Contrato do canal WhatsApp: parse de entrada e envio (T034)."""

from __future__ import annotations

import httpx
import pytest

from core.ports.channel import ChannelError
from integrations.whatsapp.client import MensagemEntrada, WhatsAppClient, parse_inbound

JID = "5511999990000@s.whatsapp.net"


def _payload(
    message: dict | None,
    *,
    from_me: bool = False,
    id: str | None = "3EB0A1",
    jid: str | None = JID,
    event: str = "messages.upsert",
) -> dict:  # type: ignore[type-arg]
    key: dict[str, object] = {"fromMe": from_me}
    if id is not None:
        key["id"] = id
    if jid is not None:
        key["remoteJid"] = jid
    data: dict[str, object] = {"key": key}
    if message is not None:
        data["message"] = message
    return {"event": event, "data": data}


def test_texto_simples() -> None:
    assert parse_inbound(_payload({"conversation": "Oi"})) == MensagemEntrada(
        JID, "3EB0A1", "texto", "Oi"
    )


def test_texto_estendido() -> None:
    r = parse_inbound(_payload({"extendedTextMessage": {"text": "Resposta citada"}}))
    assert r is not None and (r.tipo, r.conteudo) == ("texto", "Resposta citada")


@pytest.mark.parametrize(
    "mensagem",
    [
        {"audioMessage": {"url": "x"}},
        {"imageMessage": {}},
        {"stickerMessage": {}},
        {"documentMessage": {}},
        {},
        {"conversation": ""},
    ],
)
def test_qualquer_outro_tipo_e_nao_texto_com_conteudo_vazio(mensagem: dict) -> None:  # type: ignore[type-arg]
    r = parse_inbound(_payload(mensagem))
    assert r is not None and (r.tipo, r.conteudo) == ("nao_texto", "")


def test_sem_campo_message_e_nao_texto() -> None:
    r = parse_inbound(_payload(None))
    assert r is not None and r.tipo == "nao_texto"


def test_from_me_e_ignorado() -> None:
    assert parse_inbound(_payload({"conversation": "oi"}, from_me=True)) is None


@pytest.mark.parametrize("evento", ["connection.update", "MESSAGES_UPDATE", "send.message"])
def test_evento_que_nao_e_mensagem_e_ignorado(evento: str) -> None:
    assert parse_inbound(_payload({"conversation": "oi"}, event=evento)) is None


def test_evento_em_maiusculas_com_underscore_e_normalizado() -> None:
    assert parse_inbound(_payload({"conversation": "oi"}, event="MESSAGES_UPSERT")) is not None


def test_payload_sem_event_e_tratado_como_mensagem() -> None:
    payload = _payload({"conversation": "oi"})
    del payload["event"]
    assert parse_inbound(payload) is not None


@pytest.mark.parametrize("campos", [{"id": None}, {"jid": None}, {"id": ""}, {"jid": ""}])
def test_sem_id_ou_sem_remote_jid_e_ignorado(campos: dict) -> None:  # type: ignore[type-arg]
    assert parse_inbound(_payload({"conversation": "oi"}, **campos)) is None


@pytest.mark.parametrize("jid", ["120363@g.us", "status@broadcast"])
def test_grupos_e_status_sao_ignorados(jid: str) -> None:
    assert parse_inbound(_payload({"conversation": "oi"}, jid=jid)) is None


@pytest.mark.parametrize(
    "payload",
    [
        {"data": "texto"},
        {"data": {"key": "x"}},
        {"data": {}},
        {"event": "messages.upsert", "data": None},
    ],
)
def test_payload_malformado_e_ignorado(payload: dict) -> None:  # type: ignore[type-arg]
    assert parse_inbound(payload) is None


def test_message_que_nao_e_objeto_vira_nao_texto() -> None:
    payload = _payload(None)
    payload["data"]["message"] = "string"
    r = parse_inbound(payload)
    assert r is not None and r.tipo == "nao_texto"


# --- envio ---------------------------------------------------------------------------------------
def _cliente(handler) -> WhatsAppClient:  # type: ignore[no-untyped-def]
    return WhatsAppClient(transport=httpx.MockTransport(handler))


async def test_send_text_2xx_envia_corpo_e_cabecalho_certos() -> None:
    vistos: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vistos.append(req)
        return httpx.Response(201, json={"ok": True})

    await _cliente(handler).send_text(JID, "Olá!")
    req = vistos[0]
    assert req.method == "POST" and req.url.path.startswith("/message/sendText/")
    assert "apikey" in req.headers
    assert b"5511999990000" in req.read()


@pytest.mark.parametrize("codigo", [400, 401, 404, 500, 503])
async def test_send_text_nao_2xx_levanta_channel_error(codigo: int) -> None:
    with pytest.raises(ChannelError, match=f"http_{codigo}"):
        await _cliente(lambda req: httpx.Response(codigo)).send_text(JID, "oi")


async def test_send_text_timeout_levanta_channel_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=req)

    with pytest.raises(ChannelError, match="ReadTimeout"):
        await _cliente(handler).send_text(JID, "oi")


async def test_send_text_erro_de_conexao_levanta_channel_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("recusada", request=req)

    with pytest.raises(ChannelError):
        await _cliente(handler).send_text(JID, "oi")


async def test_provedor_nao_implementado(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "whatsapp_provider", "meta_cloud")
    cliente = _cliente(lambda req: httpx.Response(200))
    with pytest.raises(ChannelError, match="provedor_nao_implementado"):
        await cliente.send_text(JID, "oi")
    await cliente.aclose()
