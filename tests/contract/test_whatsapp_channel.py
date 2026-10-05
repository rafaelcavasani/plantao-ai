"""Contrato do canal WhatsApp: parse de entrada e envio (T034)."""

from __future__ import annotations

import dataclasses
import uuid

import httpx
import pytest

from core.ports.channel import ChannelError, ConexaoCanal, EstadoConexao
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


# --- instância ------------------------------------------------------------------------------------
def test_extrai_a_instancia_do_payload() -> None:
    payload = _payload({"conversation": "Oi"})
    payload["instance"] = "clinica-sorriso"
    r = parse_inbound(payload)
    assert r is not None and r.instance == "clinica-sorriso"


@pytest.mark.parametrize("valor", [None, 123, ["x"], {"a": 1}])
def test_instancia_ausente_ou_que_nao_e_texto_vira_string_vazia(valor: object) -> None:
    payload = _payload({"conversation": "Oi"})
    if valor is not None:
        payload["instance"] = valor
    r = parse_inbound(payload)
    assert r is not None and r.instance == ""


def test_instancia_nao_muda_o_que_e_ignorado() -> None:
    payload = _payload({"conversation": "oi"}, from_me=True)
    payload["instance"] = "x"
    assert parse_inbound(payload) is None


# --- envio ----------------------------------------------------------------------------------------
def _conexao(
    instance: str = "inst-a", api_key: str = "chave-secreta-a", provedor: str = "evolution"
) -> ConexaoCanal:
    return ConexaoCanal(
        tenant_id=uuid.uuid4(),
        canal="whatsapp",
        provedor=provedor,
        instance_name=instance,
        api_key=api_key,
    )


def _cliente(handler) -> WhatsAppClient:  # type: ignore[no-untyped-def]
    return WhatsAppClient(transport=httpx.MockTransport(handler))


async def test_send_text_2xx_usa_a_instancia_e_a_chave_da_conexao() -> None:
    vistos: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vistos.append(req)
        return httpx.Response(201, json={"ok": True})

    await _cliente(handler).send_text(_conexao(), JID, "Olá!")
    req = vistos[0]
    assert req.method == "POST" and req.url.path == "/message/sendText/inst-a"
    assert req.headers["apikey"] == "chave-secreta-a"
    assert b"5511999990000" in req.read()


async def test_duas_conexoes_enviam_com_chaves_diferentes() -> None:
    vistos: list[tuple[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vistos.append((req.url.path, req.headers["apikey"]))
        return httpx.Response(201)

    cliente = _cliente(handler)
    await cliente.send_text(_conexao("inst-a", "chave-a"), JID, "um")
    await cliente.send_text(_conexao("inst-b", "chave-b"), JID, "dois")
    await cliente.send_text(_conexao("inst-a", "chave-a"), JID, "tres")
    assert vistos == [
        ("/message/sendText/inst-a", "chave-a"),
        ("/message/sendText/inst-b", "chave-b"),
        ("/message/sendText/inst-a", "chave-a"),
    ]


@pytest.mark.parametrize("codigo", [400, 401, 404, 500, 503])
async def test_send_text_nao_2xx_levanta_channel_error(codigo: int) -> None:
    with pytest.raises(ChannelError, match=f"http_{codigo}") as info:
        await _cliente(lambda req: httpx.Response(codigo)).send_text(_conexao(), JID, "oi")
    assert "chave-secreta-a" not in str(info.value)


async def test_send_text_timeout_levanta_channel_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=req)

    with pytest.raises(ChannelError, match="ReadTimeout"):
        await _cliente(handler).send_text(_conexao(), JID, "oi")


async def test_send_text_erro_de_conexao_nao_vaza_a_chave() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("recusada pelo servidor", request=req)

    with pytest.raises(ChannelError) as info:
        await _cliente(handler).send_text(_conexao(), JID, "oi")
    assert str(info.value) == "ConnectError"


async def test_provedor_nao_implementado() -> None:
    cliente = _cliente(lambda req: httpx.Response(200))
    with pytest.raises(ChannelError, match="provedor_nao_implementado:meta_cloud"):
        await cliente.send_text(_conexao(provedor="meta_cloud"), JID, "oi")
    await cliente.aclose()


# --- verificação do estado da instância -------------------------------------------------------------
@pytest.mark.parametrize(
    ("corpo", "esperado"),
    [
        ({"instance": {"instanceName": "inst-a", "state": "open"}}, EstadoConexao.CONECTADA),
        ({"state": "open"}, EstadoConexao.CONECTADA),
        ({"instance": {"state": "close"}}, EstadoConexao.DESCONECTADA),
        ({"instance": {"state": "connecting"}}, EstadoConexao.DESCONECTADA),
        ({"instance": {}}, EstadoConexao.DESCONHECIDA),
        ({"qualquer": "coisa"}, EstadoConexao.DESCONHECIDA),
    ],
)
async def test_verificar_interpreta_o_estado(corpo: dict, esperado: EstadoConexao) -> None:  # type: ignore[type-arg]
    vistos: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vistos.append(req)
        return httpx.Response(200, json=corpo)

    assert await _cliente(handler).verificar(_conexao()) == esperado
    assert vistos[0].method == "GET"
    assert vistos[0].url.path == "/instance/connectionState/inst-a"
    assert vistos[0].headers["apikey"] == "chave-secreta-a"


async def test_verificar_instancia_inexistente_levanta_channel_error() -> None:
    with pytest.raises(ChannelError, match="http_404"):
        await _cliente(lambda req: httpx.Response(404)).verificar(_conexao())


async def test_verificar_erro_de_rede_levanta_channel_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("recusada", request=req)

    with pytest.raises(ChannelError, match="ConnectError"):
        await _cliente(handler).verificar(_conexao())


async def test_verificar_resposta_que_nao_e_json_levanta_channel_error() -> None:
    with pytest.raises(ChannelError):
        await _cliente(lambda req: httpx.Response(200, content=b"<html>")).verificar(_conexao())


# --- credencial fora de repr e str ------------------------------------------------------------------
def test_repr_da_conexao_nao_mostra_a_chave() -> None:
    conexao = _conexao(api_key="chave-super-secreta")
    assert "chave-super-secreta" not in repr(conexao)
    assert "chave-super-secreta" not in str(conexao)
    assert "inst-a" in repr(conexao)


def test_conexao_e_imutavel() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _conexao().api_key = "outra"  # type: ignore[misc]
