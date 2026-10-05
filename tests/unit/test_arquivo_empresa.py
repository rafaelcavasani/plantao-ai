"""Esquema do arquivo de onboarding (T038; contracts/onboarding-file.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from core.tenancy.onboarding import ArquivoEmpresa, ArquivoInvalido, carregar_arquivo

SEGREDO = "s" * 40
CHAVE = "chave-evolution-de-teste"


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("T_API_KEY", CHAVE)
    monkeypatch.setenv("T_WEBHOOK_SECRET", SEGREDO)


def _dados(**mudancas: Any) -> dict[str, Any]:
    dados: dict[str, Any] = {
        "slug": "clinica-sorriso",
        "nome_empresa": "Clínica Sorriso",
        "nicho": "clinica_odontologica",
        "canal": {
            "tipo": "whatsapp",
            "provedor": "evolution",
            "instance_name": "clinica-sorriso",
            "api_key_env": "T_API_KEY",
            "webhook_secret_env": "T_WEBHOOK_SECRET",
        },
    }
    dados.update(mudancas)
    return dados


def _erros(dados: dict[str, Any], tmp_path: Path) -> list[str]:
    arquivo = tmp_path / "empresa.yml"
    arquivo.write_text(yaml.safe_dump(dados, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ArquivoInvalido) as exc:
        carregar_arquivo(arquivo)
    return exc.value.erros


def test_arquivo_minimo_e_valido_e_usa_os_padroes() -> None:
    arquivo = ArquivoEmpresa.model_validate(_dados())
    assert arquivo.plano == "recepcionista" and arquivo.documentos is None
    assert arquivo.configuracao.handoff_ttl_minutos == 60
    assert arquivo.campos_de_config_informados() == {}


def test_so_os_campos_informados_sao_tocados() -> None:
    arquivo = ArquivoEmpresa.model_validate(
        _dados(configuracao={"tom_de_voz": "Cordial", "min_similarity": 0.4})
    )
    assert arquivo.campos_de_config_informados() == {"tom_de_voz": "Cordial", "min_similarity": 0.4}


def test_campo_desconhecido_e_recusado(tmp_path: Path) -> None:
    erros = _erros(_dados(nome_empresa_errado="x"), tmp_path)
    assert any(e.startswith("nome_empresa_errado:") for e in erros)


def test_campo_desconhecido_na_configuracao_e_recusado(tmp_path: Path) -> None:
    erros = _erros(_dados(configuracao={"tom": "x"}), tmp_path)
    assert any(e.startswith("configuracao.tom:") for e in erros)


@pytest.mark.parametrize(
    "slug", ["Clinica", "clinica_sorriso", "-clinica", "clinica-", "a b", "ab"]
)
def test_slug_invalido(slug: str, tmp_path: Path) -> None:
    assert any(e.startswith("slug:") for e in _erros(_dados(slug=slug), tmp_path))


def test_slug_longo_demais(tmp_path: Path) -> None:
    assert any(e.startswith("slug:") for e in _erros(_dados(slug="a" * 64), tmp_path))


def test_um_erro_por_campo_invalido(tmp_path: Path) -> None:
    erros = _erros(
        _dados(
            configuracao={
                "confianca_minima_handoff": 1.5,
                "limite_desconto_percentual": 120,
                "horario_funcionamento": {"seg_sex": "8h-18h"},
            }
        ),
        tmp_path,
    )
    campos = sorted(e.split(":")[0] for e in erros)
    assert campos == [
        "configuracao.confianca_minima_handoff",
        "configuracao.horario_funcionamento.seg_sex",
        "configuracao.limite_desconto_percentual",
    ] or campos == [
        "configuracao.confianca_minima_handoff",
        "configuracao.horario_funcionamento",
        "configuracao.limite_desconto_percentual",
    ]


@pytest.mark.parametrize("faixa", ["08:00-18:00", "00:00-23:59"])
def test_horario_valido(faixa: str) -> None:
    ArquivoEmpresa.model_validate(_dados(configuracao={"horario_funcionamento": {"seg": faixa}}))


@pytest.mark.parametrize("faixa", ["8:00-18:00", "08:00", "25:00-26:00", "08:00-18:60", ""])
def test_horario_invalido(faixa: str, tmp_path: Path) -> None:
    erros = _erros(_dados(configuracao={"horario_funcionamento": {"seg": faixa}}), tmp_path)
    assert any(e.startswith("configuracao.horario_funcionamento") for e in erros)


@pytest.mark.parametrize(("campo", "valor"), [("tipo", "instagram"), ("provedor", "meta_cloud")])
def test_canal_so_aceita_whatsapp_e_evolution(campo: str, valor: str, tmp_path: Path) -> None:
    dados = _dados()
    dados["canal"][campo] = valor
    assert any(e.startswith(f"canal.{campo}:") for e in _erros(dados, tmp_path))


@pytest.mark.parametrize("env", ["T_API_KEY", "T_WEBHOOK_SECRET"])
def test_variavel_ausente_cita_so_o_nome(
    env: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(env)
    erros = " ".join(_erros(_dados(), tmp_path))
    assert env in erros and CHAVE not in erros and SEGREDO not in erros


def test_variavel_vazia_e_recusada(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("T_API_KEY", "")
    assert any(e.startswith("canal.api_key_env:") for e in _erros(_dados(), tmp_path))


def test_segredo_de_entrega_curto_nao_vaza_o_valor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("T_WEBHOOK_SECRET", "curto-demais-123")
    erros = _erros(_dados(), tmp_path)
    texto = " ".join(erros)
    assert any(e.startswith("canal.webhook_secret_env:") for e in erros)
    assert "T_WEBHOOK_SECRET" in texto and "curto-demais-123" not in texto


def test_pasta_de_documentos_precisa_existir(tmp_path: Path) -> None:
    erros = _erros(_dados(documentos={"pasta": "./nao-existe"}), tmp_path)
    assert any(e.startswith("documentos.pasta:") for e in erros)


def test_pasta_de_documentos_e_relativa_ao_arquivo(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    arquivo = tmp_path / "empresa.yml"
    arquivo.write_text(yaml.safe_dump(_dados(documentos={"pasta": "./docs"})), encoding="utf-8")
    assert carregar_arquivo(arquivo).base == tmp_path.resolve()


def test_esperado_nao_aceita_texto_vazio(tmp_path: Path) -> None:
    erros = _erros(_dados(teste_prontidao={"pergunta": "Oi?", "esperado": ["ok", ""]}), tmp_path)
    assert any(e.startswith("teste_prontidao.esperado") for e in erros)


def test_arquivo_inexistente_e_yaml_quebrado(tmp_path: Path) -> None:
    with pytest.raises(ArquivoInvalido):
        carregar_arquivo(tmp_path / "nao-existe.yml")
    quebrado = tmp_path / "q.yml"
    quebrado.write_text("a: [", encoding="utf-8")
    with pytest.raises(ArquivoInvalido):
        carregar_arquivo(quebrado)


@pytest.mark.parametrize(
    ("arquivo", "variaveis"),
    [
        ("empresa-modelo.yml", ("SORRISO_EVOLUTION_API_KEY", "SORRISO_WEBHOOK_SECRET")),
        ("piloto.yml", ("PILOTO_API_KEY", "PILOTO_WEBHOOK_SECRET")),
    ],
)
def test_arquivos_de_exemplo_sao_validos_e_sem_segredos(
    arquivo: str, variaveis: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(variaveis[0], CHAVE)
    monkeypatch.setenv(variaveis[1], SEGREDO)
    caminho = Path(__file__).resolve().parents[2] / "docs" / "exemplos" / arquivo
    # sem contexto de pasta: o modelo aponta para uma pasta que cada operador cria
    carregado = ArquivoEmpresa.model_validate(yaml.safe_load(caminho.read_text(encoding="utf-8")))
    assert carregado.teste_prontidao is not None and carregado.documentos is not None
    assert CHAVE not in caminho.read_text(encoding="utf-8")


def test_pasta_de_documentos_do_piloto_existe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PILOTO_API_KEY", CHAVE)
    monkeypatch.setenv("PILOTO_WEBHOOK_SECRET", SEGREDO)
    caminho = Path(__file__).resolve().parents[2] / "docs" / "exemplos" / "piloto.yml"
    assert carregar_arquivo(caminho).documentos is not None
