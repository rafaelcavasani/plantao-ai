"""Testes de core/security/crypto.py (T010)."""

import pytest
from cryptography.fernet import Fernet, InvalidToken

from core.security.crypto import CriptoPII


def _cripto(hash_key: str = "chave-hash") -> CriptoPII:
    return CriptoPII(Fernet.generate_key().decode(), hash_key)


def test_round_trip_fernet() -> None:
    cripto = _cripto()
    token = cripto.encrypt("5511999990000@s.whatsapp.net")
    assert "5511999990000" not in token
    assert cripto.decrypt(token) == "5511999990000@s.whatsapp.net"


def test_fernet_nao_decifra_com_outra_chave() -> None:
    token = _cripto().encrypt("segredo")
    with pytest.raises(InvalidToken):
        _cripto().decrypt(token)


def test_hmac_deterministico() -> None:
    cripto = _cripto()
    assert cripto.hash_contato("5511999990000") == cripto.hash_contato("5511999990000")
    assert len(cripto.hash_contato("5511999990000")) == 64


def test_hmac_difere_por_contato_e_por_chave() -> None:
    cripto = _cripto("chave-1")
    assert cripto.hash_contato("5511999990000") != cripto.hash_contato("5511999990001")
    assert cripto.hash_contato("5511999990000") != _cripto("chave-2").hash_contato("5511999990000")


def test_chaves_ausentes_falham() -> None:
    with pytest.raises(RuntimeError):
        CriptoPII("", "x")
    with pytest.raises(RuntimeError):
        CriptoPII(Fernet.generate_key().decode(), "")
