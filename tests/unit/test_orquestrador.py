"""Orquestrador: roteamento, handoffs e guardrails de saída (T038, T043, T044), sem banco."""

from __future__ import annotations

import uuid

import pytest

from agents.orchestrator.graph import Grafo
from agents.orchestrator.state import ConfigTenant, EntradaMensagem
from core.handoff.textos import TEXTO_HANDOFF, TEXTO_NAO_TEXTO
from core.llm.ports import Finalidade, LLMError
from tests.fakes.conhecimento import buscar_fixo, json_roteador, json_suporte, trecho
from tests.fakes.llm import FakeLLMClient

CFG = ConfigTenant(
    tom_de_voz="Cordial.",
    palavras_gatilho=["procon", "advogado"],
    topicos_proibidos=["garantia de resultado"],
    limite_desconto_percentual=10.0,
    confianca_minima_handoff=0.7,
    router_confidence_threshold=0.6,
)
TRECHO = trecho("Atendemos aos sábados das 8h às 12h.", similaridade=0.9, id="t1")


def _entrada(conteudo: str = "Qual o horário aos sábados?", tipo: str = "texto") -> EntradaMensagem:
    return EntradaMensagem(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), conteudo, tipo)


def _grafo(llm: FakeLLMClient, trechos=(TRECHO,), buscar=None) -> Grafo:  # type: ignore[no-untyped-def]
    return Grafo(
        llm, buscar=buscar or buscar_fixo(trechos), modelo_roteador="barato", modelo_suporte="forte"
    )


def _llm(roteador: str, suporte: str | None = None, **kw: bool) -> FakeLLMClient:
    fila = {Finalidade.ROTEADOR: [roteador]}
    if suporte is not None:
        fila[Finalidade.SUPORTE] = [suporte]
    return FakeLLMClient(fila, **kw)  # type: ignore[arg-type]


async def test_fluxo_feliz_responde() -> None:
    llm = _llm(
        json_roteador("suporte", 0.9),
        json_suporte("Atendemos aos sábados das 8h às 12h.", 0.9, ["t1"]),
    )
    d = await _grafo(llm).executar(_entrada(), CFG)
    assert d.acao == "responder" and d.motivo is None
    assert d.texto == "Atendemos aos sábados das 8h às 12h."
    assert d.intencao == "suporte" and d.intencao_confianca == 0.9
    assert llm.finalidades == [Finalidade.ROTEADOR, Finalidade.SUPORTE]
    assert llm.chamadas[0]["modelo"] == "barato" and llm.chamadas[1]["modelo"] == "forte"


@pytest.mark.parametrize("mensagem", ["Vou ao PROCON", "meu advogado vai ligar"])
async def test_palavra_gatilho_vai_para_humano_sem_chamar_llm(mensagem: str) -> None:
    llm = FakeLLMClient()
    d = await _grafo(llm).executar(_entrada(mensagem), CFG)
    assert d.acao == "handoff" and d.motivo is not None and d.motivo.startswith("palavra_gatilho:")
    assert d.texto == TEXTO_HANDOFF and llm.chamadas == [] and llm.embeds == []


async def test_mensagem_nao_texto_vai_para_humano_com_texto_proprio() -> None:
    llm = FakeLLMClient()
    d = await _grafo(llm).executar(_entrada("", "nao_texto"), CFG)
    assert (d.acao, d.motivo, d.texto) == ("handoff", "nao_texto", TEXTO_NAO_TEXTO)
    assert llm.chamadas == []


async def test_confianca_do_roteador_abaixo_do_limiar_trata_como_suporte() -> None:
    llm = _llm(
        json_roteador("venda", 0.4),
        json_suporte("Atendemos aos sábados das 8h às 12h.", 0.9, ["t1"]),
    )
    d = await _grafo(llm).executar(_entrada(), CFG)
    assert d.acao == "responder"
    assert (
        d.intencao == "venda" and d.intencao_confianca == 0.4
    )  # a classificação do LLM é preservada


async def test_confianca_igual_ao_limiar_nao_e_tratada_como_baixa() -> None:
    llm = _llm(json_roteador("venda", 0.6))
    d = await _grafo(llm).executar(_entrada(), CFG)
    assert d.motivo == "intencao_sem_agente:venda"


@pytest.mark.parametrize("intencao", ["venda", "agendamento", "cobranca", "outro"])
async def test_outras_intencoes_vao_para_humano_sem_chamar_suporte(intencao: str) -> None:
    llm = _llm(json_roteador(intencao, 0.9, ["suporte"]))
    d = await _grafo(llm).executar(_entrada(), CFG)
    assert d.acao == "handoff" and d.motivo == f"intencao_sem_agente:{intencao}"
    assert d.intencao == intencao and d.intencoes_secundarias == ["suporte"]
    assert llm.finalidades == [Finalidade.ROTEADOR] and llm.embeds == []


async def test_falha_do_roteador_gera_handoff_falha_llm() -> None:
    llm = _llm(json_roteador())
    llm = FakeLLMClient({Finalidade.ROTEADOR: [LLMError("timeout")]})
    d = await _grafo(llm).executar(_entrada(), CFG)
    assert (d.acao, d.motivo) == ("handoff", "falha_llm")


async def test_roteador_com_saida_invalida_duas_vezes_gera_falha_llm() -> None:
    llm = FakeLLMClient({Finalidade.ROTEADOR: ["lixo", "lixo"]})
    d = await _grafo(llm).executar(_entrada(), CFG)
    assert d.motivo == "falha_llm" and len(llm.chamadas) == 2


async def test_falha_de_embedding() -> None:
    async def buscar_quebrado(llm: object, **_: object) -> list:  # type: ignore[type-arg]
        raise LLMError("timeout")

    llm = _llm(json_roteador())
    d = await _grafo(llm, buscar=buscar_quebrado).executar(_entrada(), CFG)
    assert (d.acao, d.motivo) == ("handoff", "falha_embedding")
    assert d.intencao == "suporte"
    assert llm.finalidades == [Finalidade.ROTEADOR]


async def test_sem_trechos_na_base_nao_chama_o_llm_de_suporte() -> None:
    llm = _llm(json_roteador())
    d = await _grafo(llm, trechos=()).executar(_entrada(), CFG)
    assert d.motivo == "sem_resposta_na_base"
    assert llm.finalidades == [Finalidade.ROTEADOR]


async def test_llm_diz_que_nao_sabe() -> None:
    llm = _llm(json_roteador(), json_suporte("", 0.2, [], responde=False))
    d = await _grafo(llm).executar(_entrada(), CFG)
    assert d.motivo == "sem_resposta_na_base" and d.confianca == pytest.approx(0.2)


async def test_falha_do_llm_de_suporte() -> None:
    llm = FakeLLMClient(
        {Finalidade.ROTEADOR: [json_roteador()], Finalidade.SUPORTE: [LLMError("http_500")]}
    )
    d = await _grafo(llm).executar(_entrada(), CFG)
    assert d.motivo == "falha_llm"


async def test_guardrail_confianca_baixa_vai_para_humano_sem_enviar_a_resposta() -> None:
    llm = _llm(json_roteador(), json_suporte("Atendemos aos sábados das 8h às 12h.", 0.5, ["t1"]))
    d = await _grafo(llm).executar(_entrada(), CFG)
    assert d.acao == "handoff" and d.motivo == "confianca_abaixo_do_minimo"
    assert d.texto == TEXTO_HANDOFF and d.confianca == pytest.approx(0.5)


async def test_guardrail_similaridade_baixa_derruba_confianca() -> None:
    llm = _llm(json_roteador(), json_suporte("Atendemos aos sábados das 8h às 12h.", 0.99, ["t1"]))
    fraco = trecho(TRECHO.texto, similaridade=0.35, id="t1")
    d = await _grafo(llm, trechos=(fraco,)).executar(_entrada(), CFG)
    assert d.motivo == "confianca_abaixo_do_minimo"


async def test_guardrail_valor_inventado() -> None:
    llm = _llm(json_roteador(), json_suporte("A limpeza custa R$ 99,00.", 0.95, ["t1"]))
    d = await _grafo(llm).executar(_entrada(), CFG)
    assert d.acao == "handoff" and d.motivo == "valor_nao_fundamentado:R$ 99,00"


async def test_guardrail_topico_proibido() -> None:
    llm = _llm(json_roteador(), json_suporte("Temos garantia de resultado total.", 0.95, ["t1"]))
    d = await _grafo(llm).executar(_entrada(), CFG)
    assert d.motivo == "topico_proibido:garantia de resultado"


async def test_guardrail_desconto_acima_do_limite() -> None:
    t = trecho("Desconto de 30% hoje.", id="t1")
    llm = _llm(json_roteador(), json_suporte("Temos desconto de 30% hoje.", 0.95, ["t1"]))
    d = await _grafo(llm, trechos=(t,)).executar(_entrada(), CFG)
    assert d.motivo == "desconto_acima_do_limite"


async def test_busca_recebe_tenant_pergunta_e_min_similarity() -> None:
    recebido: dict[str, object] = {}

    async def espiao(llm: object, **kw: object) -> list:  # type: ignore[type-arg]
        recebido.update(kw)
        return [TRECHO]

    entrada = _entrada("Pergunta específica")
    llm = _llm(json_roteador(), json_suporte("Atendemos aos sábados das 8h às 12h.", 0.9, ["t1"]))
    await _grafo(llm, buscar=espiao).executar(
        entrada, ConfigTenant(**{**CFG.__dict__, "min_similarity": 0.42})
    )
    assert recebido["tenant_id"] == entrada.tenant_id
    assert recebido["pergunta"] == "Pergunta específica"
    assert recebido["min_similarity"] == 0.42
