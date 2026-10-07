"""Planos do painel (spec 004, T013): valor ausente nunca vira zero."""

import pytest

from core.painel import planos
from db import config_planos


@pytest.fixture
def com_valores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        config_planos.PLANOS,
        "recepcionista",
        {"nome": "Recepcionista", "orcamento_mensal_usd": 100.0, "preco_mensal_usd": 450.0},
    )


def test_plano_sem_valor_devolve_none_e_nunca_zero() -> None:
    assert planos.orcamento_do_plano("pacote_completo") is None
    assert planos.preco_do_plano("pacote_completo") is None
    assert planos.orcamento_pct(50.0, "pacote_completo") is None
    assert planos.margem_estimada("pacote_completo", 50.0, 30) is None


def test_orcamento_pct_e_custo_sobre_orcamento(com_valores: None) -> None:
    assert planos.orcamento_pct(74.2, "recepcionista") == pytest.approx(74.2)
    assert planos.orcamento_pct(0.0, "recepcionista") == 0.0
    assert planos.orcamento_pct(150.0, "recepcionista") == pytest.approx(150.0)


def test_orcamento_zero_nao_divide_por_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        config_planos.PLANOS,
        "recepcionista",
        {"nome": "R", "orcamento_mensal_usd": 0.0, "preco_mensal_usd": None},
    )
    assert planos.orcamento_pct(10.0, "recepcionista") is None


def test_margem_e_preco_proporcional_ao_periodo_menos_custo(com_valores: None) -> None:
    assert planos.margem_estimada("recepcionista", 70.0, 30) == pytest.approx(380.0)
    assert planos.margem_estimada("recepcionista", 10.0, 7) == pytest.approx(450 * 7 / 30 - 10)
    assert planos.margem_estimada("recepcionista", 1.0, 1) == pytest.approx(450 / 30 - 1)


def test_plano_desconhecido_cai_no_padrao() -> None:
    assert planos.chave_do_plano("nao-existe") == "recepcionista"
    assert planos.chave_do_plano(None) == "recepcionista"
    assert planos.nome_do_plano("nao-existe") == "Recepcionista"


def test_listar_planos_traz_as_tres_chaves() -> None:
    chaves = [p["chave"] for p in planos.listar_planos()]
    assert chaves == ["recepcionista", "recepcionista_agendador", "pacote_completo"]
