"""Guardrails de saída (T057). Cobertura 100% exigida em core/guardrails."""

import pytest

from core.guardrails import ConfigGuardrails, checar_saida

CFG = ConfigGuardrails(
    confianca_minima=0.7,
    topicos_proibidos=["garantia de resultado", "diagnóstico definitivo"],
    limite_desconto_percentual=10.0,
)
TRECHOS = [
    "Horário de funcionamento: segunda a sexta das 08:00 às 18:00. Sábado das 8h às 12h.",
    "Limpeza dental: R$ 150,00. Clareamento: R$ 1.200,00. Desconto de 10% para pagamento à vista.",
]


def _checar(
    resposta: str,
    confianca: float = 0.9,
    trechos: list[str] | None = None,
    cfg: ConfigGuardrails = CFG,
):  # type: ignore[no-untyped-def]
    return checar_saida(resposta, TRECHOS if trechos is None else trechos, confianca, cfg)


def test_aprova_resposta_fundamentada() -> None:
    r = _checar("Abrimos aos sábados das 8h às 12h. A limpeza custa R$ 150,00.")
    assert r.aprovado is True and r.motivo is None


def test_aprova_resposta_sem_valores() -> None:
    assert _checar("Claro, posso ajudar com isso.").aprovado is True


def test_confianca_abaixo_do_minimo() -> None:
    assert _checar("Abrimos às 8h.", confianca=0.69).motivo == "confianca_abaixo_do_minimo"


def test_confianca_igual_ao_minimo_aprova() -> None:
    assert _checar("Abrimos às 8h.", confianca=0.7).aprovado is True


def test_topico_proibido_com_acento_e_caixa() -> None:
    assert (
        _checar("Temos GARANTIA DE RESULTADO total.").motivo
        == "topico_proibido:garantia de resultado"
    )
    assert (
        _checar("Faremos o diagnostico definitivo.").motivo
        == "topico_proibido:diagnóstico definitivo"
    )


def test_desconto_acima_do_limite() -> None:
    r = _checar("Para você, desconto de 20% no clareamento.", trechos=["desconto de 20%"])
    assert r.motivo == "desconto_acima_do_limite"


def test_desconto_com_percentual_antes_da_palavra() -> None:
    assert (
        _checar("Ganhe 25% de desconto hoje!", trechos=["25%"]).motivo == "desconto_acima_do_limite"
    )


def test_desconto_dentro_do_limite_e_fundamentado_aprova() -> None:
    assert _checar("Há desconto de 10% para pagamento à vista.").aprovado is True


def test_desconto_decimal() -> None:
    r = _checar("Desconto de 10,5% hoje.", trechos=["10,5%"])
    assert r.motivo == "desconto_acima_do_limite"


def test_percentual_fora_de_sentenca_de_desconto_nao_dispara_limite_mas_exige_fundamento() -> None:
    r = _checar("O índice de satisfação é de 98%. Desconto de 5%.", trechos=["Desconto de 5%."])
    assert r.motivo == "valor_nao_fundamentado:98%"


def test_valor_monetario_inventado() -> None:
    r = _checar("A limpeza custa R$ 99,00.")
    assert r.motivo == "valor_nao_fundamentado:R$ 99,00"


def test_valor_monetario_equivalente_em_formatos_diferentes() -> None:
    assert _checar("A limpeza custa R$ 150.").aprovado is True
    assert _checar("O clareamento sai por R$ 1200.").aprovado is True
    assert _checar("A limpeza custa 150 reais.").aprovado is True


def test_valor_em_reais_inventado() -> None:
    assert _checar("Sai por 80 reais.").motivo == "valor_nao_fundamentado:80 reais"


def test_horario_inventado() -> None:
    r = _checar("Abrimos aos sábados das 9h às 12h.")
    assert r.motivo == "valor_nao_fundamentado:9h"


@pytest.mark.parametrize(
    "resposta",
    ["Abrimos às 08h.", "Abrimos às 8:00.", "Fechamos às 18h00.", "Das 8 horas às 18 horas."],
)
def test_horario_em_formatos_equivalentes_aprova(resposta: str) -> None:
    assert _checar(resposta).aprovado is True


def test_horario_com_minutos_inventado() -> None:
    assert _checar("Fechamos às 17h30.").motivo == "valor_nao_fundamentado:17h30"


def test_sem_trechos_qualquer_valor_e_nao_fundamentado() -> None:
    assert _checar("Custa R$ 10,00.", trechos=[]).motivo == "valor_nao_fundamentado:R$ 10,00"


def test_ordem_confianca_antes_de_topico() -> None:
    assert _checar("garantia de resultado", confianca=0.1).motivo == "confianca_abaixo_do_minimo"


def test_ordem_topico_antes_de_desconto() -> None:
    r = _checar("Garantia de resultado e desconto de 50%.")
    assert r.motivo == "topico_proibido:garantia de resultado"


def test_ordem_desconto_antes_de_valor_nao_fundamentado() -> None:
    r = _checar("Desconto de 50% e custa R$ 1,00.", trechos=[])
    assert r.motivo == "desconto_acima_do_limite"


def test_limite_zero_bloqueia_qualquer_desconto() -> None:
    cfg = ConfigGuardrails(0.7, [], 0.0)
    assert _checar("Desconto de 5%.", trechos=["5%"], cfg=cfg).motivo == "desconto_acima_do_limite"
