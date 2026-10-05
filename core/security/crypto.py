"""Criptografia e hash de dados pessoais (LGPD, princípio IV).

- `contato_enc`: Fernet (AES-128-CBC + HMAC) para recuperar o contato e enviar a resposta.
- `contato_hash`: HMAC-SHA256 determinístico para localizar a conversa sem expor o número.
"""

from __future__ import annotations

import hashlib
import hmac
from functools import lru_cache

from cryptography.fernet import Fernet

from core.config import settings


class CriptoPII:
    def __init__(self, encryption_key: str, hash_key: str) -> None:
        if not encryption_key or not hash_key:
            raise RuntimeError("PII_ENCRYPTION_KEY e PII_HASH_KEY são obrigatórias.")
        self._fernet = Fernet(encryption_key.encode())
        self._hash_key = hash_key.encode()

    def encrypt(self, texto: str) -> str:
        return self._fernet.encrypt(texto.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode()).decode()

    def hash_contato(self, contato: str) -> str:
        return hmac.new(self._hash_key, contato.encode(), hashlib.sha256).hexdigest()


@lru_cache
def get_cripto() -> CriptoPII:
    """Instância única configurada a partir das variáveis de ambiente."""
    return CriptoPII(settings.pii_encryption_key, settings.pii_hash_key)
