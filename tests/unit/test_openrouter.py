"""OpenRouterClient com transport falso (T026, R-12)."""

import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from core.llm.openrouter import OpenRouterClient
from core.llm.ports import ChamadaLLM, Finalidade, LLMError
from core.llm.pricing import estimar_custo
from tests.fakes.openrouter import OpenRouterFalso

TENANT = uuid.uuid4()
MSGS = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


class Coletor:
    def __init__(self) -> None:
        self.chamadas: list[ChamadaLLM] = []

    async def __call__(self, chamada: ChamadaLLM) -> None:
        self.chamadas.append(chamada)


async def _sem_espera(_: float) -> None:
    return None


def _cliente(falso: OpenRouterFalso, coletor: Coletor) -> OpenRouterClient:
    return OpenRouterClient(
        api_key="k",
        base_url="https://gw.test/v1",
        registrar=coletor,
        transport=falso.transport,
        sleep=_sem_espera,
    )


async def test_chat_sucesso_registra_uso_e_custo() -> None:
    falso, coletor = OpenRouterFalso(lambda _: '{"ok": true}'), Coletor()
    r = await _cliente(falso, coletor).complete_json(
        finalidade=Finalidade.ROTEADOR,
        modelo="anthropic/claude-3-haiku",
        mensagens=MSGS,
        tenant_id=TENANT,
    )
    assert r.texto == '{"ok": true}'
    assert r.uso.tokens_entrada == 120 and r.uso.tokens_saida == 30
    assert r.uso.custo_usd == estimar_custo("anthropic/claude-3-haiku", 120, 30)
    assert len(coletor.chamadas) == 1 and coletor.chamadas[0].sucesso is True
    corpo = falso.requests[0][1]
    assert corpo["response_format"] == {"type": "json_object"} and corpo["temperature"] == 0


async def test_custo_do_gateway_tem_prioridade() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.0042},
            },
        )

    cliente = OpenRouterClient(
        api_key="k",
        base_url="https://gw.test/v1",
        registrar=Coletor(),
        transport=httpx.MockTransport(handler),
    )
    r = await cliente.complete_json(
        finalidade=Finalidade.SUPORTE, modelo="x/y", mensagens=MSGS, tenant_id=TENANT
    )
    assert r.uso.custo_usd == Decimal("0.0042")


async def test_timeout_tem_1_retry_e_depois_falha() -> None:
    falso, coletor = OpenRouterFalso(lambda _: httpx.ReadTimeout("lento")), Coletor()
    with pytest.raises(LLMError) as exc:
        await _cliente(falso, coletor).complete_json(
            finalidade=Finalidade.SUPORTE, modelo="m", mensagens=MSGS, tenant_id=TENANT
        )
    assert exc.value.codigo == "timeout"
    assert len(falso.requests) == 2
    assert len(coletor.chamadas) == 1 and coletor.chamadas[0].sucesso is False
    assert coletor.chamadas[0].erro == "timeout"


async def test_5xx_tenta_de_novo_e_pode_recuperar() -> None:
    estados = iter([503, '{"ok": 1}'])
    falso, coletor = OpenRouterFalso(lambda _: next(estados)), Coletor()
    r = await _cliente(falso, coletor).complete_json(
        finalidade=Finalidade.ROTEADOR, modelo="m", mensagens=MSGS, tenant_id=TENANT
    )
    assert r.texto == '{"ok": 1}' and len(falso.requests) == 2
    assert coletor.chamadas[0].sucesso is True


async def test_5xx_persistente_falha() -> None:
    falso, coletor = OpenRouterFalso(lambda _: 502), Coletor()
    with pytest.raises(LLMError, match="http_502"):
        await _cliente(falso, coletor).complete_json(
            finalidade=Finalidade.ROTEADOR, modelo="m", mensagens=MSGS, tenant_id=TENANT
        )
    assert len(falso.requests) == 2


async def test_4xx_nao_tenta_de_novo() -> None:
    falso, coletor = OpenRouterFalso(lambda _: 401), Coletor()
    with pytest.raises(LLMError, match="http_401"):
        await _cliente(falso, coletor).complete_json(
            finalidade=Finalidade.ROTEADOR, modelo="m", mensagens=MSGS, tenant_id=TENANT
        )
    assert len(falso.requests) == 1


async def test_erro_de_rede_vira_llm_error() -> None:
    falso, coletor = OpenRouterFalso(lambda _: httpx.ConnectError("sem rede")), Coletor()
    with pytest.raises(LLMError, match="erro_de_rede"):
        await _cliente(falso, coletor).complete_json(
            finalidade=Finalidade.ROTEADOR, modelo="m", mensagens=MSGS, tenant_id=TENANT
        )


async def test_resposta_sem_choices_e_invalida() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"foo": "bar"})

    coletor = Coletor()
    cliente = OpenRouterClient(
        api_key="k",
        base_url="https://gw.test/v1",
        registrar=coletor,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LLMError, match="resposta_invalida"):
        await cliente.complete_json(
            finalidade=Finalidade.SUPORTE, modelo="m", mensagens=MSGS, tenant_id=TENANT
        )
    assert coletor.chamadas[0].erro == "resposta_invalida"


async def test_embeddings_em_ordem_e_registro() -> None:
    falso, coletor = OpenRouterFalso(), Coletor()
    r = await _cliente(falso, coletor).embed(
        textos=["horario sabado", "preco limpeza"], tenant_id=TENANT
    )
    assert len(r.vetores) == 2 and len(r.vetores[0]) == 1536
    assert coletor.chamadas[0].finalidade is Finalidade.EMBEDDING
    assert falso.requests[0][0].endswith("/embeddings")


async def test_uma_linha_em_llm_calls_por_chamada_inclusive_falha(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    """Usa o registrador real (banco): sucesso e falha geram uma linha cada."""
    from db.models import LLMCall
    from db.session import tenant_session

    estados = iter(['{"a":1}', 500, 500])
    falso = OpenRouterFalso(lambda _: next(estados))
    cliente = OpenRouterClient(
        api_key="k", base_url="https://gw.test/v1", transport=falso.transport, sleep=_sem_espera
    )
    await cliente.complete_json(
        finalidade=Finalidade.ROTEADOR, modelo="m", mensagens=MSGS, tenant_id=tenant_a
    )
    with pytest.raises(LLMError):
        await cliente.complete_json(
            finalidade=Finalidade.SUPORTE, modelo="m", mensagens=MSGS, tenant_id=tenant_a
        )
    async with tenant_session(tenant_a) as s:
        linhas = (await s.execute(select(LLMCall).order_by(LLMCall.criado_em))).scalars().all()
    assert [(c.finalidade, c.sucesso) for c in linhas] == [("roteador", True), ("suporte", False)]
    assert linhas[1].erro == "http_500"
