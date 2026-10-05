"""Datasets de avaliação e cálculo das metas (T050, T080, T081, T061)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from agents.router.schemas import Intencao
from core.guardrails.base import normalizar
from core.llm.ports import Finalidade
from scripts.run_evals import (
    EmpresaIsolamento,
    Item,
    Medida,
    Medidor,
    avaliar_isolamento,
    calcular_medidas,
    carregar_dataset,
    carregar_isolamento,
    formatar_tabela,
    principal,
)
from tests.fakes.conhecimento import inserir_conhecimento, json_roteador, json_suporte
from tests.fakes.llm import FakeLLMClient
from tests.fakes.pipeline import slug_de

DOCS = Path(__file__).resolve().parent.parent / "evals" / "docs_piloto"


def test_tamanhos_dos_datasets_seguem_o_spec() -> None:
    assert len(carregar_dataset("intencoes")) == 50
    assert len(carregar_dataset("respostas")) == 30
    assert len(carregar_dataset("sem_resposta")) == 20
    assert (
        len(carregar_dataset("adversariais")) == 21
    )  # 20 de SC-003 + o de vazamento entre empresas


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
        ({"isolamento": [_item(True)] * 89 + [_item(False)]}, "MT-002"),
        ({"isolamento": [_item(True)] * 89 + [Item(ok=True, vazou=True)]}, "MT-002x"),
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
    capsys: pytest.CaptureFixture[str],
) -> None:
    await inserir_conhecimento(
        db, tenant_a, {"h.md": ["Horário de atendimento aos sábados: 8h às 12h."]}
    )
    llm = FakeLLMClient(
        {
            Finalidade.ROTEADOR: [json_roteador("suporte", 0.95)] * 40,
            Finalidade.SUPORTE: [json_suporte("Atendemos aos sábados das 8h às 12h.", 0.95)] * 40,
        }
    )
    codigo = await principal(
        ["--tenant", await slug_de(db, tenant_a), "--suite", "sem_resposta"], llm
    )
    saida = capsys.readouterr().out
    assert "SC-002" in saida  # nenhuma pergunta casa com a base falsa: todas viram repasse
    assert codigo == 0


async def test_sem_tenant_sai_com_2_e_empresa_inexistente_com_1(
    db: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await principal(["--suite", "sem_resposta"], FakeLLMClient()) == 2
    assert "--tenant" in capsys.readouterr().err
    assert await principal(["--tenant", "nao-existe"], FakeLLMClient()) == 1
    assert "nao encontrada" in capsys.readouterr().err


# --- suíte isolamento (US3, T060/T061) --------------------------------------------------------
EVALS = Path(__file__).resolve().parent.parent / "evals"


def _corpus(pasta: str) -> str:
    return normalizar(" ".join(p.read_text(encoding="utf-8") for p in (EVALS / pasta).glob("*.md")))


def test_isolamento_tem_tres_empresas_com_30_perguntas_cada() -> None:
    empresas = carregar_isolamento()
    assert list(empresas) == ["a", "b", "c"]
    assert all(len(e["perguntas"]) == 30 for e in empresas.values())


def test_isolamento_o_esperado_esta_na_base_propria_e_os_marcadores_so_nela() -> None:
    empresas = carregar_isolamento()
    corpus = {chave: _corpus(e["docs"]) for chave, e in empresas.items()}
    for chave, e in empresas.items():
        for item in e["perguntas"]:
            assert item["esperado"], item
            for trecho in item["esperado"]:
                assert normalizar(trecho) in corpus[chave], f"{chave}: '{trecho}' ({item})"
        for marcador in e["marcadores"]:
            assert marcador == normalizar(marcador)
            assert marcador in corpus[chave], f"{chave}: marcador '{marcador}' fora da base"
            for outra, texto in corpus.items():
                assert outra == chave or marcador not in texto, f"{marcador} vaza para {outra}"


def test_documentos_das_empresas_b_e_c_nao_tem_dados_pessoais() -> None:
    import re

    for pasta in ("docs_empresa_b", "docs_empresa_c"):
        texto = " ".join(p.read_text(encoding="utf-8") for p in (EVALS / pasta).glob("*.md"))
        assert texto.strip()
        assert not re.search(
            r"\d{3}\.\d{3}\.\d{3}-\d{2}|\(\d{2}\)\s?\d{4,5}-\d{4}|@\w+\.\w+", texto
        )


class _GrafoFalso:
    """Responde com o esperado da pergunta; `vazar` acrescenta o marcador de outra empresa à resposta."""

    def __init__(self, donos: dict[uuid.UUID, str], vazar: dict[str, str] | None = None) -> None:
        self.donos = donos
        self.vazar = vazar or {}
        self.esperados = {
            (chave, p["pergunta"]): p["esperado"]
            for chave, e in carregar_isolamento().items()
            for p in e["perguntas"]
        }

    async def executar(self, entrada: object, config: object) -> SimpleNamespace:
        chave = self.donos[entrada.tenant_id]  # type: ignore[attr-defined]
        texto = " ".join(self.esperados[(chave, entrada.conteudo)])  # type: ignore[attr-defined]
        return SimpleNamespace(acao="responder", texto=f"{texto} {self.vazar.get(chave, '')}")


async def _medir_isolamento(
    db: AsyncEngine, ids: list[uuid.UUID], vazar: dict[str, str] | None = None
) -> dict[str, Medida]:
    definicoes = carregar_isolamento()
    empresas = [
        EmpresaIsolamento(chave, tenant_id, tuple(d["marcadores"]), list(d["perguntas"]))
        for (chave, d), tenant_id in zip(definicoes.items(), ids, strict=True)
    ]
    grafo = _GrafoFalso(dict(zip(ids, definicoes, strict=True)), vazar)
    itens = await avaliar_isolamento(grafo, Medidor(FakeLLMClient()), empresas)  # type: ignore[arg-type]
    return {m.codigo: m for m in calcular_medidas({"isolamento": itens})}


async def test_isolamento_sem_marcador_alheio_passa(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID, tenant_c: uuid.UUID
) -> None:
    medidas = await _medir_isolamento(db, [tenant_a, tenant_b, tenant_c])
    assert medidas["MT-002"].valor == 1.0 and medidas["MT-002x"].valor == 0.0
    assert all(m.ok for m in medidas.values())


async def test_isolamento_marcador_alheio_faz_a_meta_falhar(
    db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID, tenant_c: uuid.UUID
) -> None:
    medidas = await _medir_isolamento(
        db, [tenant_a, tenant_b, tenant_c], vazar={"b": "A Clínica Sorriso também faz isso."}
    )
    assert medidas["MT-002x"].ok is False and medidas["MT-002x"].valor == pytest.approx(30 / 90)
    assert (
        medidas["MT-002"].ok is True
    )  # a resposta própria continua correta; o vazamento é outra meta


async def test_isolamento_cli_valida_argumentos_e_roda_com_llm_falso(
    db: AsyncEngine,
    tenant_a: uuid.UUID,
    tenant_b: uuid.UUID,
    tenant_c: uuid.UUID,
    capsys: pytest.CaptureFixture[str],
) -> None:
    slugs = [await slug_de(db, t) for t in (tenant_a, tenant_b, tenant_c)]
    assert await principal(["--suite", "isolamento"], FakeLLMClient()) == 2
    assert "--tenants" in capsys.readouterr().err
    assert await principal(["--suite", "isolamento", "--tenants", slugs[0]], FakeLLMClient()) == 2
    assert await principal(["--suite", "isolamento", "--tenants", "x,y,z"], FakeLLMClient()) == 1
    capsys.readouterr()

    llm = FakeLLMClient(
        {
            Finalidade.ROTEADOR: [json_roteador("suporte", 0.95)] * 100,
            Finalidade.SUPORTE: [json_suporte("Sem base.", 0.95)] * 100,
        }
    )
    codigo = await principal(["--suite", "isolamento", "--tenants", ",".join(slugs)], llm)
    saida = capsys.readouterr().out
    assert "MT-002" in saida and "MT-002x" in saida
    assert codigo == 1  # empresas sem documentos: nenhuma resposta própria correta
