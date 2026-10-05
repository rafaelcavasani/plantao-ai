"""Regras puras da prontidão (T039; research R-10)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.tenancy.config import ConfigEmpresa
from core.tenancy.prontidao import avaliar_resposta_teste, config_completa, conversa_teste_valida

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _config(**campos: object) -> ConfigEmpresa:
    base: dict[str, object] = {
        "tom_de_voz": "Cordial",
        "horario_funcionamento": {"seg_sex": "08:00-18:00"},
    }
    return ConfigEmpresa(**{**base, **campos})


def test_config_completa_com_tom_e_horario() -> None:
    assert config_completa(_config())


@pytest.mark.parametrize("tom", ["", "   "])
def test_tom_de_voz_vazio_nao_e_completa(tom: str) -> None:
    assert not config_completa(_config(tom_de_voz=tom))


def test_horario_vazio_nao_e_completa() -> None:
    assert not config_completa(_config(horario_funcionamento={}))


def test_configuracao_padrao_nao_e_completa() -> None:
    assert not config_completa(ConfigEmpresa())


def test_teste_aprovado_e_mais_novo_que_tudo_vale() -> None:
    assert conversa_teste_valida(True, T0, T0 - timedelta(minutes=1), T0 - timedelta(minutes=2))


def test_sem_alteracoes_o_teste_aprovado_vale() -> None:
    assert conversa_teste_valida(True, T0, None, None)


def test_teste_reprovado_ou_ausente_nao_vale() -> None:
    assert not conversa_teste_valida(False, T0, None, None)
    assert not conversa_teste_valida(True, None, None, None)


def test_config_alterada_depois_do_teste_invalida() -> None:
    assert not conversa_teste_valida(True, T0, T0 + timedelta(seconds=1), None)


def test_documento_atualizado_depois_do_teste_invalida() -> None:
    assert not conversa_teste_valida(True, T0, None, T0 + timedelta(seconds=1))


def test_alteracao_no_mesmo_instante_invalida() -> None:
    assert not conversa_teste_valida(True, T0, T0, None)


def test_responder_com_todos_os_termos_aprova() -> None:
    assert avaliar_resposta_teste("responder", "Abrimos das 08:00 às 12:00.", ["08:00", "12:00"])


def test_comparacao_ignora_caixa_e_acentos() -> None:
    assert avaliar_resposta_teste("responder", "Atendemos no SÁBADO.", ["sabado"])


def test_termo_faltando_reprova() -> None:
    assert not avaliar_resposta_teste("responder", "Abrimos das 08:00.", ["08:00", "12:00"])


def test_sem_termos_qualquer_resposta_aprova() -> None:
    assert avaliar_resposta_teste("responder", "Qualquer coisa.", [])


def test_handoff_reprova_mesmo_sem_termos() -> None:
    assert not avaliar_resposta_teste("handoff", "Vou chamar um atendente.", [])
