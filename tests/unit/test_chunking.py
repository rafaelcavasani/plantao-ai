"""Divisão em trechos e extração de texto (T066)."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter

from core.rag.chunking import (
    SOBREPOSICAO,
    TAMANHO_TRECHO,
    FormatoNaoSuportado,
    dividir,
    extrair_texto,
)

PARAGRAFO = "O horário de funcionamento da clínica é de segunda a sexta, das 8h às 18h. "


def test_parametros_do_plano() -> None:
    assert (TAMANHO_TRECHO, SOBREPOSICAO) == (800, 100)


@pytest.mark.parametrize("texto", ["", "   ", "\n\n\t"])
def test_texto_vazio_nao_gera_trechos(texto: str) -> None:
    assert dividir(texto) == []


def test_texto_curto_vira_um_unico_trecho() -> None:
    assert dividir("Sábado das 8h às 12h.") == ["Sábado das 8h às 12h."]


def test_texto_longo_respeita_o_tamanho_maximo_e_a_sobreposicao() -> None:
    texto = PARAGRAFO * 60
    trechos = dividir(texto)
    assert len(trechos) > 1
    assert all(len(t) <= TAMANHO_TRECHO for t in trechos)
    # há sobreposição: o começo de cada trecho aparece no fim do anterior
    for anterior, atual in zip(trechos, trechos[1:], strict=False):
        assert atual[:30].strip() in anterior


def test_nenhum_trecho_e_vazio() -> None:
    assert all(t.strip() for t in dividir("A\n\n\n\nB\n\n" + PARAGRAFO * 30))


def test_extrai_texto_de_txt_e_md_com_acentos() -> None:
    assert extrair_texto("a.txt", "Atendimento às 8h".encode()) == "Atendimento às 8h"
    assert extrair_texto("B.MD", "# Título".encode()) == "# Título"


def test_bytes_invalidos_em_utf8_nao_quebram() -> None:
    assert "ol" in extrair_texto("a.txt", b"ol\xe1")


def test_pdf_sem_camada_de_texto_devolve_vazio() -> None:
    escritor = PdfWriter()
    escritor.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    escritor.write(buffer)
    assert extrair_texto("scan.pdf", buffer.getvalue()).strip() == ""


def test_extensao_nao_suportada() -> None:
    with pytest.raises(FormatoNaoSuportado):
        extrair_texto("planilha.xlsx", b"x")
    with pytest.raises(FormatoNaoSuportado):
        extrair_texto("semextensao", b"x")
