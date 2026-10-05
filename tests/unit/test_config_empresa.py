"""Validação da configuração por empresa (FR-008, FR-009)."""

import pytest
from pydantic import ValidationError

from core.tenancy import ConfigEmpresa
from db.config_padrao import CONFIG_PADRAO, nova_config_padrao


def _campos_invalidos(exc: ValidationError) -> set[str]:
    return {str(e["loc"][0]) for e in exc.errors()}


def test_aceita_os_valores_padrao() -> None:
    config = ConfigEmpresa(**CONFIG_PADRAO)
    assert config.handoff_ttl_minutos == 60
    assert config.limite_mensagens_por_minuto == 60


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("confianca_minima_handoff", 1.1),
        ("confianca_minima_handoff", -0.1),
        ("router_confidence_threshold", 1.5),
        ("min_similarity", -0.01),
        ("limite_desconto_percentual", 100.5),
        ("limite_desconto_percentual", -1),
        ("handoff_ttl_minutos", 0),
        ("handoff_ttl_minutos", 1441),
        ("limite_mensagens_por_minuto", 0),
        ("limite_mensagens_por_minuto", 6001),
    ],
)
def test_recusa_valor_fora_da_faixa(campo: str, valor: float) -> None:
    with pytest.raises(ValidationError) as info:
        ConfigEmpresa(**{**CONFIG_PADRAO, campo: valor})
    assert _campos_invalidos(info.value) == {campo}


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("confianca_minima_handoff", 0),
        ("confianca_minima_handoff", 1),
        ("limite_desconto_percentual", 0),
        ("limite_desconto_percentual", 100),
        ("handoff_ttl_minutos", 1),
        ("handoff_ttl_minutos", 1440),
        ("limite_mensagens_por_minuto", 1),
        ("limite_mensagens_por_minuto", 6000),
    ],
)
def test_aceita_os_limites_da_faixa(campo: str, valor: float) -> None:
    ConfigEmpresa(**{**CONFIG_PADRAO, campo: valor})


def test_informa_cada_campo_invalido() -> None:
    with pytest.raises(ValidationError) as info:
        ConfigEmpresa(
            **{
                **CONFIG_PADRAO,
                "confianca_minima_handoff": 2,
                "limite_desconto_percentual": 150,
                "handoff_ttl_minutos": 0,
            }
        )
    assert _campos_invalidos(info.value) == {
        "confianca_minima_handoff",
        "limite_desconto_percentual",
        "handoff_ttl_minutos",
    }


def test_recusa_campo_desconhecido() -> None:
    with pytest.raises(ValidationError) as info:
        ConfigEmpresa(**{**CONFIG_PADRAO, "campo_que_nao_existe": 1})
    assert _campos_invalidos(info.value) == {"campo_que_nao_existe"}


def test_empresas_criadas_do_modelo_nao_compartilham_estado() -> None:
    a = nova_config_padrao()
    b = nova_config_padrao()
    a["topicos_proibidos"].append("x")
    a["palavras_gatilho"].append("y")
    a["horario_funcionamento"]["seg"] = "08:00-12:00"
    assert b["topicos_proibidos"] == []
    assert "y" not in b["palavras_gatilho"]
    assert b["horario_funcionamento"] == {}
    assert CONFIG_PADRAO["topicos_proibidos"] == []
    assert "y" not in CONFIG_PADRAO["palavras_gatilho"]
    assert CONFIG_PADRAO["horario_funcionamento"] == {}
