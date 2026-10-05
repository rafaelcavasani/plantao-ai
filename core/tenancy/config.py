"""Validação da configuração por empresa (FR-008, FR-009).

`ConfigEmpresa` é o contrato de valores aceitos; os CHECKs de `tenant_config` repetem as faixas no banco
como defesa em profundidade.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from core.tenancy.auditoria import registrar_mudanca
from db.config_padrao import CONFIG_PADRAO, PALAVRAS_GATILHO_PADRAO
from db.models import TenantConfig

_FAIXA_HORARIO: Final = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")

Probabilidade = Annotated[float, Field(ge=0, le=1)]


class ConfigEmpresa(BaseModel):
    """Configuração de uma empresa. Campos desconhecidos e valores fora da faixa são recusados."""

    model_config = ConfigDict(extra="forbid")

    tom_de_voz: str = CONFIG_PADRAO["tom_de_voz"]
    horario_funcionamento: dict[str, str] = Field(default_factory=dict)
    limite_desconto_percentual: Annotated[float, Field(ge=0, le=100)] = CONFIG_PADRAO[
        "limite_desconto_percentual"
    ]
    topicos_proibidos: list[str] = Field(default_factory=list)
    confianca_minima_handoff: Probabilidade = CONFIG_PADRAO["confianca_minima_handoff"]
    palavras_gatilho: list[str] = Field(default_factory=lambda: list(PALAVRAS_GATILHO_PADRAO))
    router_confidence_threshold: Probabilidade = CONFIG_PADRAO["router_confidence_threshold"]
    min_similarity: Probabilidade = CONFIG_PADRAO["min_similarity"]
    handoff_ttl_minutos: Annotated[int, Field(ge=1, le=1440)] = CONFIG_PADRAO["handoff_ttl_minutos"]
    limite_mensagens_por_minuto: Annotated[int, Field(ge=1, le=6000)] = CONFIG_PADRAO[
        "limite_mensagens_por_minuto"
    ]

    @field_validator("horario_funcionamento")
    @classmethod
    def _horario_valido(cls, valor: dict[str, str]) -> dict[str, str]:
        for chave, faixa in valor.items():
            if not _FAIXA_HORARIO.match(faixa):
                raise ValueError(f"{chave}: use o formato HH:MM-HH:MM")
        return valor

    @field_validator("palavras_gatilho", "topicos_proibidos")
    @classmethod
    def _textos_nao_vazios(cls, valor: list[str]) -> list[str]:
        if any(not item.strip() for item in valor):
            raise ValueError("a lista nao pode ter textos vazios")
        return valor

    def como_dict(self) -> dict[str, Any]:
        return self.model_dump()


CAMPOS_CONFIG: tuple[str, ...] = tuple(ConfigEmpresa.model_fields)


class ConfigInvalida(ValueError):
    """Alteração recusada. `erros` traz um item `campo: motivo` por campo inválido."""

    def __init__(self, erros: list[str]) -> None:
        super().__init__("; ".join(erros))
        self.erros = erros


def interpretar_atribuicoes(pares: Sequence[str]) -> dict[str, Any]:
    """Converte `campo=valor` em dict. O valor é JSON (`0.8`, `["a"]`, `{"k": "v"}`); sem JSON válido, texto.

    Recusa (`ConfigInvalida`) par sem `=`, campo vazio e campo repetido, listando todos os problemas.
    """
    saida: dict[str, Any] = {}
    erros: list[str] = []
    for par in pares:
        campo, separador, bruto = par.partition("=")
        campo = campo.strip()
        if not separador or not campo:
            erros.append(f"{par or '(vazio)'}: use campo=valor")
            continue
        if campo in saida:
            erros.append(f"{campo}: informado mais de uma vez")
            continue
        try:
            saida[campo] = json.loads(bruto)
        except ValueError:
            saida[campo] = bruto
    if erros:
        raise ConfigInvalida(erros)
    return saida


def erros_de_validacao(exc: ValidationError, prefixo: str = "") -> list[str]:
    """Um texto `campo: motivo` por erro do pydantic, sem eco do valor recebido."""
    saida: list[str] = []
    for erro in exc.errors():
        campo = ".".join(str(parte) for parte in erro["loc"])
        mensagem = erro["msg"].removeprefix("Value error, ")
        saida.append(f"{prefixo}{campo}: {mensagem}" if campo else f"{prefixo}{mensagem}")
    return saida


def valores_da_config(linha: TenantConfig) -> dict[str, Any]:
    """Os campos de `ConfigEmpresa` lidos de uma linha de `tenant_config`."""
    return {campo: getattr(linha, campo) for campo in CAMPOS_CONFIG}


async def aplicar_alteracoes(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    alteracoes: Mapping[str, Any],
    operador: str,
) -> list[str]:
    """Valida o conjunto inteiro, grava só o que mudou e audita um campo por linha.

    Na mesma transação da `session` (sem commit). Valor inválido recusa **tudo** (`ConfigInvalida`) e
    nada é gravado. Devolve os nomes dos campos realmente alterados.
    """
    desconhecidos = [c for c in alteracoes if c not in CAMPOS_CONFIG]
    if desconhecidos:
        raise ConfigInvalida([f"{c}: campo desconhecido" for c in desconhecidos])
    linha = await session.get(TenantConfig, tenant_id)
    if linha is None:
        raise LookupError("empresa sem configuracao")
    atual = valores_da_config(linha)
    try:
        validada = ConfigEmpresa(**{**atual, **alteracoes}).como_dict()
    except ValidationError as exc:
        raise ConfigInvalida(erros_de_validacao(exc)) from exc
    alterados: list[str] = []
    for campo in alteracoes:
        if validada[campo] != atual[campo]:
            await registrar_mudanca(
                session, tenant_id, "config", campo, atual[campo], validada[campo], operador
            )
            setattr(linha, campo, validada[campo])
            alterados.append(campo)
    if alterados:
        await session.flush()
    return alterados
