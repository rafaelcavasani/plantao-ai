"""Autenticação do painel (spec 004, T014; ADR-0007, FR-001, FR-006)."""

import hashlib
import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fakeredis import FakeAsyncRedis
from jwt.algorithms import RSAAlgorithm

from apps.api.admin.auth import (
    SessaoStore,
    desafio_pkce,
    parse_operadores,
    validar_id_token,
)
from apps.api.admin.schemas import ErroAdmin
from core.config import Settings, settings

ISSUER = "https://idp.exemplo.com"
AUDIENCE = "cliente-123"
NONCE = "nonce-abc"


@pytest.fixture
def redis() -> FakeAsyncRedis:
    return FakeAsyncRedis()


@pytest.fixture
def operadores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings, "operadores", "Voce@Exemplo.com:operacao, leitor@exemplo.com:leitura"
    )


# --- OPERADORES ----------------------------------------------------------------------------------


def test_parse_operadores_normaliza_e_valida() -> None:
    assert parse_operadores("Voce@Exemplo.com:operacao, leitor@exemplo.com:leitura") == {
        "voce@exemplo.com": "operacao",
        "leitor@exemplo.com": "leitura",
    }
    assert parse_operadores("") == {}


@pytest.mark.parametrize("texto", ["a@b.com:admin", "a@b.com", "semarroba:leitura", ":leitura"])
def test_operadores_invalidos_falham(texto: str) -> None:
    with pytest.raises(ValueError, match="OPERADORES"):
        parse_operadores(texto)


# --- Sessão --------------------------------------------------------------------------------------


async def test_sessao_guarda_so_o_hash_do_token(redis: FakeAsyncRedis, operadores: None) -> None:
    store = SessaoStore(redis)
    token = await store.criar("voce@exemplo.com", "operacao")
    chaves = [k.decode() async for k in redis.scan_iter(match="painel:sessao:*")]
    assert chaves == ["painel:sessao:" + hashlib.sha256(token.encode()).hexdigest()]
    assert token not in chaves[0] and len(token) >= 40


async def test_sessao_valida_devolve_operador_e_renova(
    redis: FakeAsyncRedis, operadores: None
) -> None:
    store = SessaoStore(redis)
    t0 = 1_000_000.0
    token = await store.criar("voce@exemplo.com", "operacao", agora=t0)
    op = await store.obter(token, agora=t0 + 600)
    assert op is not None and (op.email, op.papel) == ("voce@exemplo.com", "operacao")
    assert op.pode_operar
    # Renovou: 25 min depois da renovação ainda vale (60 min depois do início, mas só 25 de inatividade).
    assert await store.obter(token, agora=t0 + 600 + 25 * 60) is not None


async def test_sessao_expira_por_inatividade_de_30_minutos(
    redis: FakeAsyncRedis, operadores: None
) -> None:
    store = SessaoStore(redis)
    t0 = 1_000_000.0
    token = await store.criar("voce@exemplo.com", "operacao", agora=t0)
    assert await store.obter(token, agora=t0 + 31 * 60) is None
    assert await store.obter(token, agora=t0 + 60) is None  # e foi apagada, não revive


async def test_sessao_expira_no_teto_de_12_horas_mesmo_com_uso(
    redis: FakeAsyncRedis, operadores: None
) -> None:
    store = SessaoStore(redis)
    t0 = 1_000_000.0
    token = await store.criar("voce@exemplo.com", "operacao", agora=t0)
    t = t0
    while t < t0 + 12 * 3600:
        t += 20 * 60
        assert await store.obter(token, agora=t) is not None
    assert await store.obter(token, agora=t + 20 * 60) is None


async def test_quem_sai_da_lista_perde_a_sessao_e_o_papel_acompanha_a_lista(
    redis: FakeAsyncRedis, operadores: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessaoStore(redis)
    token = await store.criar("voce@exemplo.com", "operacao")
    monkeypatch.setattr(settings, "operadores", "voce@exemplo.com:leitura")
    op = await store.obter(token)
    assert op is not None and op.papel == "leitura" and not op.pode_operar
    monkeypatch.setattr(settings, "operadores", "outro@exemplo.com:operacao")
    assert await store.obter(token) is None


async def test_token_vazio_ou_desconhecido(redis: FakeAsyncRedis, operadores: None) -> None:
    store = SessaoStore(redis)
    assert await store.obter(None) is None
    assert await store.obter("") is None
    assert await store.obter("inexistente") is None


async def test_apagar_encerra_a_sessao(redis: FakeAsyncRedis, operadores: None) -> None:
    store = SessaoStore(redis)
    token = await store.criar("voce@exemplo.com", "operacao")
    await store.apagar(token)
    assert await store.obter(token) is None


# --- id_token ------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def chave() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks(chave: rsa.RSAPrivateKey, kid: str = "k1") -> dict[str, Any]:
    publica = json.loads(RSAAlgorithm.to_jwk(chave.public_key()))
    return {"keys": [{**publica, "kid": kid, "use": "sig", "alg": "RS256"}]}


def _token(chave: rsa.RSAPrivateKey, **sobrescrever: Any) -> str:
    agora = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "u1",
        "iat": agora,
        "exp": agora + 300,
        "nonce": NONCE,
        "email": "voce@exemplo.com",
        "email_verified": True,
    }
    claims.update(sobrescrever)
    return jwt.encode(
        {k: v for k, v in claims.items() if v is not None}, chave, "RS256", headers={"kid": "k1"}
    )


def _validar(chave: rsa.RSAPrivateKey, token: str, **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "jwks": _jwks(chave),
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "nonce": NONCE,
    }
    args.update(kw)
    return validar_id_token(token, **args)


def test_id_token_valido(chave: rsa.RSAPrivateKey) -> None:
    assert _validar(chave, _token(chave))["email"] == "voce@exemplo.com"


@pytest.mark.parametrize(
    "mudanca",
    [
        {"iss": "https://outro.com"},
        {"aud": "outro-cliente"},
        {"exp": 1},
        {"nonce": "outro"},
        {"nonce": None},
        {"iat": None},
    ],
)
def test_id_token_com_claim_errada_e_recusado(
    chave: rsa.RSAPrivateKey, mudanca: dict[str, Any]
) -> None:
    with pytest.raises(ErroAdmin) as exc:
        _validar(chave, _token(chave, **mudanca))
    assert exc.value.status == 401


def test_id_token_assinado_por_outra_chave_e_recusado(chave: rsa.RSAPrivateKey) -> None:
    outra = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ErroAdmin) as exc:
        _validar(chave, _token(outra))
    assert exc.value.status == 401


def test_id_token_com_kid_desconhecido_e_recusado(chave: rsa.RSAPrivateKey) -> None:
    with pytest.raises(ErroAdmin) as exc:
        _validar(chave, _token(chave), jwks=_jwks(chave, kid="outro"))
    assert exc.value.status == 401


def test_id_token_alg_none_e_recusado(chave: rsa.RSAPrivateKey) -> None:
    sem_assinatura = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": "x"}, None, algorithm="none"
    )
    with pytest.raises(ErroAdmin):
        _validar(chave, sem_assinatura)


@pytest.mark.parametrize(
    "email", [{"email_verified": False}, {"email_verified": None}, {"email": None}]
)
def test_id_token_sem_email_verificado_e_recusado(
    chave: rsa.RSAPrivateKey, email: dict[str, Any]
) -> None:
    with pytest.raises(ErroAdmin) as exc:
        _validar(chave, _token(chave, **email))
    assert exc.value.status == 403


def test_desafio_pkce_e_o_sha256_em_base64_url() -> None:
    # Vetor de teste da RFC 7636, apêndice B.
    assert (
        desafio_pkce("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
        == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


# --- Modo de desenvolvimento ---------------------------------------------------------------------


def test_modo_dev_fora_de_development_impede_a_subida(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(env="production", painel_auth_mode="dev", pii_encryption_key="a", pii_hash_key="b")
    with pytest.raises(RuntimeError, match="PAINEL_AUTH_MODE=dev"):
        s.exigir_segredos()
    ok = Settings(
        env="development", painel_auth_mode="dev", pii_encryption_key="a", pii_hash_key="b"
    )
    ok.exigir_segredos()


def test_modo_de_autenticacao_desconhecido_impede_a_subida() -> None:
    s = Settings(
        env="development", painel_auth_mode="qualquer", pii_encryption_key="a", pii_hash_key="b"
    )
    with pytest.raises(RuntimeError, match="PAINEL_AUTH_MODE"):
        s.exigir_segredos()
