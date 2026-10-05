"""Divisão de documentos em trechos e extração de texto (R-06)."""

from __future__ import annotations

import io
from pathlib import PurePath

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

TAMANHO_TRECHO = 800
SOBREPOSICAO = 100
EXTENSOES_TEXTO = {".txt", ".md"}
EXTENSOES_SUPORTADAS = EXTENSOES_TEXTO | {".pdf"}

_divisor = RecursiveCharacterTextSplitter(chunk_size=TAMANHO_TRECHO, chunk_overlap=SOBREPOSICAO)


class FormatoNaoSuportado(Exception):
    """Extensão fora de `.txt`, `.md` e `.pdf`."""


def dividir(texto: str) -> list[str]:
    """Trechos de até 800 caracteres com 100 de sobreposição. Texto vazio ou só espaços gera `[]`."""
    if not texto.strip():
        return []
    return [t for t in _divisor.split_text(texto) if t.strip()]


def extrair_texto(nome: str, conteudo: bytes) -> str:
    """Texto do arquivo. PDF sem camada de texto devolve string vazia. Levanta `FormatoNaoSuportado`."""
    extensao = PurePath(nome).suffix.lower()
    if extensao in EXTENSOES_TEXTO:
        return conteudo.decode("utf-8", errors="replace")
    if extensao == ".pdf":
        leitor = PdfReader(io.BytesIO(conteudo))
        return "\n".join((pagina.extract_text() or "") for pagina in leitor.pages)
    raise FormatoNaoSuportado(extensao or nome)
