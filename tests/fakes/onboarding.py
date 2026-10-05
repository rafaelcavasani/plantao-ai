"""Auxiliares dos testes de onboarding: arquivo de empresa, variáveis de credencial e pasta de documentos."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

SEGREDO_ENTREGA = "entrega-" + "x" * 40
CHAVE_ENVIO = "chave-de-envio-secreta-123"
DOCUMENTOS = {
    "faq.md": "Atendemos aos sábados das 08:00 às 12:00.",
    "precos.md": "A consulta de avaliação custa R$ 150,00.",
}


def escrever_empresa(
    pasta: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    slug: str = "clinica-nova",
    instance: str | None = None,
    documentos: dict[str, str] | None = DOCUMENTOS,
    configuracao: dict[str, Any] | None = None,
    teste: dict[str, Any] | None = None,
    prefixo_env: str = "NOVA",
) -> Path:
    """Escreve `<slug>.yml` (e a pasta de documentos) em `pasta` e define as variáveis de credencial."""
    monkeypatch.setenv(f"{prefixo_env}_API_KEY", CHAVE_ENVIO)
    monkeypatch.setenv(f"{prefixo_env}_WEBHOOK_SECRET", SEGREDO_ENTREGA)
    dados: dict[str, Any] = {
        "slug": slug,
        "nome_empresa": f"Empresa {slug}",
        "nicho": "clinica_odontologica",
        "configuracao": configuracao
        if configuracao is not None
        else {
            "tom_de_voz": "Cordial e direto.",
            "horario_funcionamento": {"seg_sex": "08:00-18:00", "sabado": "08:00-12:00"},
        },
        "canal": {
            "tipo": "whatsapp",
            "provedor": "evolution",
            "instance_name": instance or slug,
            "api_key_env": f"{prefixo_env}_API_KEY",
            "webhook_secret_env": f"{prefixo_env}_WEBHOOK_SECRET",
        },
    }
    if documentos is not None:
        pasta_docs = pasta / f"docs-{slug}"
        pasta_docs.mkdir(exist_ok=True)
        for nome, texto in documentos.items():
            (pasta_docs / nome).write_text(texto, encoding="utf-8")
        dados["documentos"] = {"pasta": f"./docs-{slug}"}
    if teste is not None:
        dados["teste_prontidao"] = teste
    arquivo = pasta / f"{slug}.yml"
    arquivo.write_text(yaml.safe_dump(dados, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return arquivo
