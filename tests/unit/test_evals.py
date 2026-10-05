"""Datasets de avaliação e cálculo das metas (T050, T080, T081)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from agents.router.schemas import Intencao
from core.config import settings
from core.guardrails.base import normalizar
from core.llm.ports import Finalidade
from scripts.run_evals import (
    Item,
    Medida,
    calcular_medidas,
    carregar_dataset,
    formatar_tabela,
    principal,
)
from tests.fakes.conhecimento import inserir_conhecimento, json_roteador, json_suporte
from tests.fakes.llm import FakeLLMClient

DOCS = Path(__file__).resolve().parent.parent / "evals" / "docs_piloto"


def test_tamanhos_dos_datasets_seguem_o_spec() -> None:
    assert len(carregar_dataset("intencoes")) == 50
    assert len(carregar_dataset("respostas")) == 30
    assert len(carregar_dataset("sem_resposta")) == 20
    assert len(carregar_dataset("adversariais")) == 20


def test_intencoes_rotuladas_sao_validas_e_cobrem_as_cinco_classes() -> None:
    itens = carregar_dataset("intencoes")
    rotulos = {i["intencao"] for i in itens}
    assert rotulos == {e.value for e in Intencao}
    assert all(i["mensagem"].strip() for i in itens)
    assert all(i.get("secundaria", "suporte") in {e.value for e in Intencao} for i in itens)


def test_perguntas_com_resposta_tem_o_esperado_nos_documentos_do_piloto() -> None:
    corpus = normalizar(" ".join(p.read_text(encoding="utf-8") for p in DOCS.glob("*.md")))
    for item in carregar_dataset("respostas"):
        assert item["esperado"], item
        for trecho in item["esperado"]:
            assert normalizar(trecho) in corpus, (
                f"'{trecho}' não está nos documentos ({item['pergunta']})"
            )


def test_documentos_do_piloto_nao_tem_dados_pessoais() -> None:
    import re

    texto = " ".join(p.read_text(encoding="utf-8") for p in DOCS.glob("*.md"))
    assert not re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}|\(\d{2}\)\s?\d{4,5}-\d{4}|@\w+\.\w+", texto)


def test_adversariais_declaram_o_que_nao_pode_aparecer() -> None:
    assert all("nao_deve_conter" in i and i["mensagem"] for i in carregar_dataset("adversariais"))


def _item(ok: bool, handoff: bool = False, lat: float = 1.0, custo: str = "0.001") -> Item:
    return Item(ok=ok, handoff=handoff, latencia_s=lat, custo_usd=Decimal(custo))


def test_calculo_das_metas_aprovado() -> None:
    medidas = {
        m.codigo: m
        for m in calcular_medidas(
            {
                "respostas": [_item(True)] * 27 + [_item(False, handoff=True)] * 3,
                "sem_resposta": [_item(True, handoff=True)] * 20,
                "adversariais": [_item(True, handoff=True)] * 20,
                "intencoes": [_item(True)] * 46 + [_item(False)] * 4,
            }
        )
    }
    assert set(medidas) == {"SC-001", "SC-002", "SC-003", "SC-004", "SC-005", "SC-006", "SC-009"}
    assert all(m.ok for m in medidas.values())
    assert medidas["SC-001"].valor == pytest.approx(0.9) and medidas[
        "SC-009"
    ].valor == pytest.approx(0.1)


@pytest.mark.parametrize(
    ("resultados", "codigo"),
    [
        ({"respostas": [_item(True)] * 25 + [_item(False)] * 5}, "SC-001"),
        ({"respostas": [_item(True, lat=11.0)] * 30}, "SC-004"),
        ({"respostas": [_item(True, custo="0.02")] * 30}, "SC-006"),
        ({"respostas": [_item(True, handoff=True)] * 30}, "SC-009"),
        ({"sem_resposta": [_item(True)] * 19 + [_item(False)]}, "SC-002"),
        ({"adversariais": [_item(True)] * 19 + [_item(False)]}, "SC-003"),
        ({"intencoes": [_item(True)] * 44 + [_item(False)] * 6}, "SC-005"),
    ],
)
def test_cada_meta_falha_quando_o_limite_e_violado(
    resultados: dict[str, list[Item]], codigo: str
) -> None:
    medidas = {m.codigo: m for m in calcular_medidas(resultados)}
    assert medidas[codigo].ok is False


def test_so_mede_o_que_foi_executado() -> None:
    assert {m.codigo for m in calcular_medidas({"intencoes": [_item(True)]})} == {"SC-005"}


def test_tabela_mostra_resultado_por_meta() -> None:
    tabela = formatar_tabela(
        [Medida("SC-001", "x", 0.9, 0.85, ">="), Medida("SC-006", "custo", 0.02, 0.01, "<")]
    )
    linhas = tabela.splitlines()
    assert linhas[1].startswith("SC-001") and linhas[1].endswith("OK") and "90.0%" in linhas[1]
    assert linhas[2].endswith("FALHOU") and "0.0200" in linhas[2]


async def test_execucao_ponta_a_ponta_com_llm_falso(
    db: AsyncEngine,
    tenant_a: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(settings, "pilot_tenant_id", str(tenant_a))
    await inserir_conhecimento(
        db, tenant_a, {"h.md": ["Horário de atendimento aos sábados: 8h às 12h."]}
    )
    llm = FakeLLMClient(
        {
            Finalidade.ROTEADOR: [json_roteador("suporte", 0.95)] * 40,
            Finalidade.SUPORTE: [json_suporte("Atendemos aos sábados das 8h às 12h.", 0.95)] * 40,
        }
    )
    codigo = await principal(["--suite", "sem_resposta"], llm)
    saida = capsys.readouterr().out
    assert "SC-002" in saida  # nenhuma pergunta casa com a base falsa: todas viram repasse
    assert codigo == 0
