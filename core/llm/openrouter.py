"""Cliente de LLM e embeddings via OpenRouter (única porta para modelos, constituição I).

Protocolo compatível com a API da OpenAI (`/chat/completions`, `/embeddings`). Timeout de 15 s e 1 retry
com backoff de 1 s, apenas em erro de rede, timeout ou 5xx (R-12). Uma linha em `llm_calls` por chamada
lógica, inclusive falhas.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal
from typing import Any

import httpx

from core.config import settings
from core.llm.ports import ChamadaLLM, EmbedResult, Finalidade, LLMError, LLMResult, Mensagem, Uso
from core.llm.pricing import estimar_custo
from core.llm.registro import Registrador, gravar_chamada

Sleeper = Callable[[float], Awaitable[None]]


class OpenRouterClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        embedding_model: str | None = None,
        registrar: Registrador = gravar_chamada,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.openrouter_api_key
        self._embedding_model = embedding_model or settings.embedding_model
        self._registrar = registrar
        self._sleep = sleep
        self._http = httpx.AsyncClient(
            base_url=base_url or settings.openrouter_base_url,
            timeout=timeout if timeout is not None else settings.llm_timeout_seconds,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def complete_json(
        self,
        *,
        finalidade: Finalidade,
        modelo: str,
        mensagens: Sequence[Mensagem],
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID | None = None,
        message_id: uuid.UUID | None = None,
    ) -> LLMResult:
        corpo = {
            "model": modelo,
            "messages": list(mensagens),
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }

        def extrair(data: dict[str, Any]) -> str:
            return str(data["choices"][0]["message"]["content"])

        texto, uso = await self._chamar(
            "/chat/completions",
            corpo,
            modelo,
            finalidade,
            tenant_id,
            conversation_id,
            message_id,
            extrair,
        )
        return LLMResult(texto=texto, modelo=modelo, uso=uso)

    async def embed(
        self,
        *,
        textos: Sequence[str],
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID | None = None,
        message_id: uuid.UUID | None = None,
    ) -> EmbedResult:
        corpo = {"model": self._embedding_model, "input": list(textos)}

        def extrair(data: dict[str, Any]) -> list[list[float]]:
            itens = sorted(data["data"], key=lambda i: i["index"])
            vetores = [[float(x) for x in item["embedding"]] for item in itens]
            if len(vetores) != len(textos):
                raise ValueError("quantidade de vetores diferente da de textos")
            return vetores

        vetores, uso = await self._chamar(
            "/embeddings",
            corpo,
            self._embedding_model,
            Finalidade.EMBEDDING,
            tenant_id,
            conversation_id,
            message_id,
            extrair,
        )
        return EmbedResult(vetores=vetores, modelo=self._embedding_model, uso=uso)

    async def _chamar(
        self,
        caminho: str,
        corpo: dict[str, Any],
        modelo: str,
        finalidade: Finalidade,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        message_id: uuid.UUID | None,
        extrair: Callable[[dict[str, Any]], Any],
    ) -> tuple[Any, Uso]:
        inicio = time.perf_counter()
        erro: str | None = None
        uso = Uso()
        resultado: Any = None
        try:
            data = await self._post_com_retry(caminho, corpo)
            try:
                resultado = extrair(data)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise LLMError("resposta_invalida") from exc
            uso = self._uso(data, modelo, inicio)
        except LLMError as exc:
            erro = exc.codigo
            uso = Uso(latencia_ms=int((time.perf_counter() - inicio) * 1000))
            raise
        finally:
            await self._registrar(
                ChamadaLLM(
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    finalidade=finalidade,
                    modelo=modelo,
                    sucesso=erro is None,
                    uso=uso,
                    erro=erro,
                )
            )
        return resultado, uso

    async def _post_com_retry(self, caminho: str, corpo: dict[str, Any]) -> dict[str, Any]:
        ultimo_erro = "desconhecido"
        for tentativa in range(2):
            if tentativa:
                await self._sleep(1.0)
            try:
                resposta = await self._http.post(
                    caminho, json=corpo, headers={"Authorization": f"Bearer {self._api_key}"}
                )
            except httpx.TimeoutException:
                ultimo_erro = "timeout"
                continue
            except httpx.TransportError:
                ultimo_erro = "erro_de_rede"
                continue
            if resposta.status_code >= 500:
                ultimo_erro = f"http_{resposta.status_code}"
                continue
            if resposta.status_code >= 400:
                raise LLMError(f"http_{resposta.status_code}")
            try:
                data = resposta.json()
            except ValueError as exc:
                raise LLMError("resposta_invalida") from exc
            if not isinstance(data, dict):
                raise LLMError("resposta_invalida")
            return data
        raise LLMError(ultimo_erro)

    @staticmethod
    def _uso(data: dict[str, Any], modelo: str, inicio: float) -> Uso:
        bruto = data.get("usage") or {}
        tokens_in = int(bruto.get("prompt_tokens", 0) or 0)
        tokens_out = int(bruto.get("completion_tokens", 0) or 0)
        custo_gateway = bruto.get("cost")
        custo = (
            Decimal(str(custo_gateway))
            if custo_gateway is not None
            else estimar_custo(modelo, tokens_in, tokens_out)
        )
        return Uso(
            tokens_entrada=tokens_in,
            tokens_saida=tokens_out,
            custo_usd=custo,
            latencia_ms=int((time.perf_counter() - inicio) * 1000),
        )
