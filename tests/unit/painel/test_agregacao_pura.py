"""Funções puras da agregação do painel (spec 004, T016; research R-12 e R-13)."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from core.painel.agregacao import (
    BALDES_RESPOSTA_S,
    balde_da_resposta,
    inicio_da_hora,
    media_ms,
    p95_s,
    somar_histogramas,
)

SAO_PAULO = timezone(timedelta(hours=-3))


def test_baldes_sao_onze_posicoes() -> None:
    assert BALDES_RESPOSTA_S == (1, 2, 3, 5, 8, 13, 21, 34, 55, 89)


@pytest.mark.parametrize(
    ("segundos", "indice"),
    [
        (0.0, 0),
        (1.0, 0),
        (1.01, 1),
        (2.0, 1),
        (3.0, 2),
        (4.9, 3),
        (5.0, 3),
        (8.0, 4),
        (13.0, 5),
        (21.0, 6),
        (34.0, 7),
        (55.0, 8),
        (89.0, 9),
        (89.01, 10),
        (3600.0, 10),
    ],
)
def test_balde_da_resposta(segundos: float, indice: int) -> None:
    assert balde_da_resposta(segundos) == indice


def test_somar_histogramas_soma_posicao_a_posicao() -> None:
    a = [1, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0]
    b = [0, 3, 0, 0, 0, 0, 0, 0, 0, 0, 5]
    assert somar_histogramas([a, b]) == [1, 3, 2, 0, 0, 0, 0, 0, 0, 0, 5]
    assert somar_histogramas([]) == [0] * 11


def test_media_ms() -> None:
    assert media_ms(2, 43000) == 21500.0
    assert media_ms(0, 0) is None


def test_p95_sem_dados_e_none() -> None:
    assert p95_s([0] * 11) is None


def test_p95_e_o_limite_do_balde_onde_o_acumulado_passa_de_95_por_cento() -> None:
    # 100 respostas: 94 em <=1 s, 5 em <=3 s, 1 em <=21 s. O acumulado cruza 95% no balde de 3 s.
    hist = [94, 0, 5, 0, 0, 0, 1, 0, 0, 0, 0]
    assert p95_s(hist) == 3.0
    # Todas rápidas: p95 = 1 s.
    assert p95_s([10] + [0] * 10) == 1.0
    # Cauda lenta passando de 5%: o p95 sobe para o balde da cauda.
    assert p95_s([90, 0, 0, 0, 0, 0, 10, 0, 0, 0, 0]) == 21.0


def test_p95_no_ultimo_balde_fica_no_teto_de_89_segundos() -> None:
    assert p95_s([0] * 10 + [4]) == 89.0


def test_inicio_da_hora_em_utc() -> None:
    assert inicio_da_hora(datetime(2026, 10, 6, 12, 47, 33, 999, tzinfo=UTC)) == datetime(
        2026, 10, 6, 12, 0, tzinfo=UTC
    )
    # 22:30 em São Paulo (UTC-3) é 01:30 do dia seguinte em UTC.
    assert inicio_da_hora(datetime(2026, 10, 6, 22, 30, tzinfo=SAO_PAULO)) == datetime(
        2026, 10, 7, 1, 0, tzinfo=UTC
    )
