"""Tabela de transições do estado da empresa (FR-011)."""

import pytest

from core.tenancy import Estado, TransicaoInvalida, validar_transicao

VALIDAS = [
    ("em_configuracao", "ativo"),
    ("em_configuracao", "encerrado"),
    ("ativo", "suspenso"),
    ("ativo", "encerrado"),
    ("suspenso", "ativo"),
    ("suspenso", "encerrado"),
]


@pytest.mark.parametrize(("de", "para"), VALIDAS)
def test_transicao_valida(de: str, para: str) -> None:
    validar_transicao(Estado(de), Estado(para))


def test_aceita_texto_puro_como_estado() -> None:
    validar_transicao("ativo", "suspenso")


@pytest.mark.parametrize(
    ("de", "para"),
    [(de, para) for de in Estado for para in Estado if (de.value, para.value) not in VALIDAS],
)
def test_transicao_invalida(de: Estado, para: Estado) -> None:
    with pytest.raises(TransicaoInvalida):
        validar_transicao(de, para)


@pytest.mark.parametrize("novo", [e for e in Estado if e is not Estado.ENCERRADO])
def test_encerrado_nao_volta(novo: Estado) -> None:
    with pytest.raises(TransicaoInvalida):
        validar_transicao(Estado.ENCERRADO, novo)


def test_mensagem_cita_estado_atual_e_permitidos() -> None:
    with pytest.raises(TransicaoInvalida) as info:
        validar_transicao(Estado.ATIVO, Estado.EM_CONFIGURACAO)
    assert str(info.value) == (
        "Transicao invalida: ativo -> em_configuracao. "
        "Permitido a partir de ativo: suspenso, encerrado."
    )


def test_mensagem_do_estado_final() -> None:
    with pytest.raises(TransicaoInvalida) as info:
        validar_transicao(Estado.ENCERRADO, Estado.ATIVO)
    assert "Permitido a partir de encerrado: nenhum." in str(info.value)


def test_estado_desconhecido_e_recusado() -> None:
    with pytest.raises(ValueError):
        validar_transicao("trial", Estado.ATIVO)
