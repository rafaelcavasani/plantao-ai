"""Embedding falso e determinístico para testes: bag-of-words por hashing em 1536 dimensões.

Textos com palavras em comum têm similaridade de cosseno alta; textos sem palavras em comum, zero.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata

DIM = 1536
_STOP = {
    "de",
    "da",
    "do",
    "das",
    "dos",
    "a",
    "o",
    "as",
    "os",
    "e",
    "em",
    "no",
    "na",
    "que",
    "um",
    "uma",
    "para",
    "por",
    "com",
    "se",
    "voce",
    "voces",
}


def _tokens(texto: str) -> list[str]:
    sem_acento = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return [t for t in re.findall(r"[a-z0-9]+", sem_acento) if t not in _STOP]


def embed_falso(texto: str) -> list[float]:
    vetor = [0.0] * DIM
    for token in _tokens(texto):
        indice = int(hashlib.md5(token.encode()).hexdigest()[:8], 16) % DIM
        vetor[indice] += 1.0
    norma = math.sqrt(sum(v * v for v in vetor)) or 1.0
    return [v / norma for v in vetor]
