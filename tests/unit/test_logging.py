"""Logging estruturado e máscara de PII (T067)."""

from __future__ import annotations

import io
import json
import logging

import pytest

from core.observability.logging import (
    FiltroPII,
    FormatadorJson,
    configurar_observabilidade,
    definir_contexto,
    limpar_contexto,
)


@pytest.fixture
def saida() -> io.StringIO:
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(FormatadorJson())
    handler.addFilter(FiltroPII())
    logger = logging.getLogger("teste.logging")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    limpar_contexto()
    yield buffer
    limpar_contexto()


def _linha(saida: io.StringIO) -> dict[str, object]:
    return json.loads(saida.getvalue().strip().splitlines()[-1])  # type: ignore[no-any-return]


def test_linha_e_json_com_campos_basicos(saida: io.StringIO) -> None:
    logging.getLogger("teste.logging").info("evento ocorreu")
    linha = _linha(saida)
    assert linha["mensagem"] == "evento ocorreu" and linha["nivel"] == "INFO"
    assert linha["logger"] == "teste.logging" and "ts" in linha


def test_contexto_aparece_em_todas_as_linhas(saida: io.StringIO) -> None:
    definir_contexto(
        correlation_id="c1", tenant_id="t1", conversation_id="v1", ignorado="x", nulo=None
    )
    logging.getLogger("teste.logging").info("a")
    linha = _linha(saida)
    assert (linha["correlation_id"], linha["tenant_id"], linha["conversation_id"]) == (
        "c1",
        "t1",
        "v1",
    )
    assert "ignorado" not in linha and "nulo" not in linha


def test_telefone_na_mensagem_e_nos_argumentos_e_mascarado(saida: io.StringIO) -> None:
    logging.getLogger("teste.logging").info("contato %s", "+55 (11) 99999-0000")
    texto = saida.getvalue()
    assert "99999-0000" not in texto and "999990000" not in texto


def test_telefone_em_dados_extras_e_mascarado(saida: io.StringIO) -> None:
    logging.getLogger("teste.logging").info(
        "x", extra={"dados": {"contato": "5511999990000@s.whatsapp.net"}}
    )
    assert "999990000" not in saida.getvalue()


def test_excecao_vai_para_campo_erro_mascarado(saida: io.StringIO) -> None:
    try:
        raise ValueError("falha com 5511999990000")
    except ValueError:
        logging.getLogger("teste.logging").exception("deu ruim")
    linha = _linha(saida)
    assert "ValueError" in str(linha["erro"]) and "999990000" not in saida.getvalue()


def test_configurar_observabilidade_instala_handler_json() -> None:
    raiz = logging.getLogger()
    antigos, nivel = raiz.handlers[:], raiz.level
    try:
        configurar_observabilidade()
        assert len(raiz.handlers) == 1 and isinstance(raiz.handlers[0].formatter, FormatadorJson)
    finally:
        raiz.handlers, raiz.level = antigos, nivel
