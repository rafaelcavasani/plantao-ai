"""Regras de atenção do painel (spec 004, T032; FR-011 e FR-012)."""

import pytest

from core.config import settings
from core.painel.atencao import (
    AMOSTRA_MINIMA_CONVERSAS,
    EntradaAtencao,
    Limites,
    avaliar,
    limites_atuais,
)

LIMITES = Limites(silencio_horas=24, handoff_pct=30, custo_pct=90)


def entrada(**kw: object) -> EntradaAtencao:
    base: dict[str, object] = {
        "estado": "ativo",
        "minutos_desde_ultima": 5.0,
        "minutos_desde_ativacao": 10_000.0,
        "conversas": 100,
        "handoffs": 10,
        "falhas_envio": 0,
        "conexao": "verificada",
        "orcamento_pct": 50.0,
    }
    base.update(kw)
    return EntradaAtencao(**base)  # type: ignore[arg-type]


def codigos(e: EntradaAtencao) -> list[str]:
    return [a.codigo for a in avaliar(e, LIMITES)]


def test_empresa_saudavel_nao_alerta() -> None:
    assert avaliar(entrada(), LIMITES) == []


def test_sem_atividade_so_para_empresa_ativa_acima_de_24_horas() -> None:
    assert codigos(entrada(minutos_desde_ultima=24 * 60)) == []  # exatamente no limite não alerta
    achado = avaliar(entrada(minutos_desde_ultima=26 * 60), LIMITES)
    assert [a.codigo for a in achado] == ["sem_atividade"]
    assert "26 h" in achado[0].detalhe
    for estado in ("suspenso", "em_configuracao"):
        assert codigos(entrada(estado=estado, minutos_desde_ultima=30 * 60)) == []


def test_sem_mensagens_nunca_usa_a_ativacao_como_referencia() -> None:
    assert codigos(entrada(minutos_desde_ultima=None, minutos_desde_ativacao=60.0)) == []
    achado = avaliar(entrada(minutos_desde_ultima=None, minutos_desde_ativacao=48 * 60.0), LIMITES)
    assert achado[0].codigo == "sem_atividade" and "desde a ativação" in achado[0].detalhe
    assert codigos(entrada(minutos_desde_ultima=None, minutos_desde_ativacao=None)) == []


def test_handoff_alto_acima_de_30_por_cento_das_conversas() -> None:
    assert codigos(entrada(conversas=100, handoffs=30)) == []  # igual ao limite não alerta
    achado = avaliar(entrada(conversas=255, handoffs=96), LIMITES)
    assert achado[0].codigo == "handoff_alto"
    assert "37,6%" in achado[0].detalhe and "limite 30%" in achado[0].detalhe


def test_handoff_ignora_amostra_pequena() -> None:
    pouco = AMOSTRA_MINIMA_CONVERSAS - 1
    assert codigos(entrada(conversas=pouco, handoffs=pouco)) == []
    assert codigos(
        entrada(conversas=AMOSTRA_MINIMA_CONVERSAS, handoffs=AMOSTRA_MINIMA_CONVERSAS)
    ) == ["handoff_alto"]
    assert codigos(entrada(conversas=0, handoffs=0)) == []


def test_custo_alto_em_90_por_cento_ou_mais_do_orcamento() -> None:
    assert codigos(entrada(orcamento_pct=89.9)) == []
    achado = avaliar(entrada(orcamento_pct=92.0), LIMITES)
    assert achado[0].codigo == "custo_alto" and achado[0].gravidade == "aviso"
    assert avaliar(entrada(orcamento_pct=90.0), LIMITES)[0].codigo == "custo_alto"
    assert avaliar(entrada(orcamento_pct=130.0), LIMITES)[0].gravidade == "critica"


def test_plano_sem_orcamento_nunca_dispara_alerta_de_custo() -> None:
    assert codigos(entrada(orcamento_pct=None)) == []


def test_conexao_nao_verificada_alerta_so_empresa_ativa() -> None:
    assert codigos(entrada(conexao="nao_verificada")) == ["conexao_nao_verificada"]
    assert avaliar(entrada(conexao="sem_conexao"), LIMITES)[0].detalhe == "sem conexão do canal"
    assert codigos(entrada(estado="em_configuracao", conexao="sem_conexao")) == []


def test_falhas_de_envio() -> None:
    achado = avaliar(entrada(falhas_envio=3), LIMITES)
    assert achado[0].codigo == "falhas_envio" and "3 falha(s)" in achado[0].detalhe


def test_empresa_encerrada_nunca_alerta() -> None:
    assert (
        avaliar(
            entrada(estado="encerrado", conexao="sem_conexao", falhas_envio=9, orcamento_pct=500.0),
            LIMITES,
        )
        == []
    )


def test_ordem_critica_primeiro() -> None:
    achados = avaliar(
        entrada(
            conexao="nao_verificada",
            minutos_desde_ultima=40 * 60,
            falhas_envio=1,
            orcamento_pct=120.0,
        ),
        LIMITES,
    )
    gravidades = [a.gravidade for a in achados]
    assert gravidades == sorted(gravidades, key=lambda g: 0 if g == "critica" else 1)
    assert achados[0].gravidade == "critica"


def test_limites_vem_da_configuracao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "painel_limite_silencio_horas", 12)
    monkeypatch.setattr(settings, "painel_limite_handoff_pct", 20.0)
    monkeypatch.setattr(settings, "painel_limite_custo_pct", 80.0)
    assert limites_atuais() == Limites(12, 20.0, 80.0)
    assert [a.codigo for a in avaliar(entrada(minutos_desde_ultima=13 * 60), limites_atuais())] == [
        "sem_atividade"
    ]


def test_valores_padrao_sao_24h_30_e_90() -> None:
    assert limites_atuais() == Limites(24, 30.0, 90.0)
