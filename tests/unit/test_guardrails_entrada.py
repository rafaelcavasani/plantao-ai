"""Guardrails de entrada (T056). Cobertura 100% exigida em core/guardrails."""

import pytest

from core.guardrails import checar_entrada

GATILHOS = ["processo", "procon", "cancelar tudo", "advogado", "reclamação"]


def test_aprova_pergunta_normal() -> None:
    assert checar_entrada("Que horas vocês abrem no sábado?", "texto", GATILHOS).aprovado is True


@pytest.mark.parametrize(
    "mensagem",
    [
        "Vou chamar o PROCON",
        "vou abrir um processo contra voces",
        "Quero CANCELAR TUDO",
        "falei com meu Advogado",
        "tenho uma reclamacao",
        "RECLAMAÇÃO formal",
    ],
)
def test_palavra_gatilho_com_caixa_e_acento_variados(mensagem: str) -> None:
    r = checar_entrada(mensagem, "texto", GATILHOS)
    assert r.aprovado is False
    assert r.motivo is not None and r.motivo.startswith("palavra_gatilho:")


def test_motivo_traz_o_termo_configurado() -> None:
    assert checar_entrada("vou ao Procon", "texto", GATILHOS).motivo == "palavra_gatilho:procon"


def test_nao_texto() -> None:
    r = checar_entrada("", "nao_texto", GATILHOS)
    assert (r.aprovado, r.motivo) == (False, "nao_texto")


@pytest.mark.parametrize("mensagem", ["", "   ", "😀", "👍👍", "?!...", "\n"])
def test_mensagem_vazia_ou_so_emoji(mensagem: str) -> None:
    r = checar_entrada(mensagem, "texto", GATILHOS)
    assert (r.aprovado, r.motivo) == (False, "mensagem_vazia")


def test_sem_gatilhos_configurados_aprova() -> None:
    assert checar_entrada("vou ao procon", "texto", []).aprovado is True
