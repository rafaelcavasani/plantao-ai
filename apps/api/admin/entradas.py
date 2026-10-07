"""Modelos de entrada das rotas de escrita (contrato: contracts/admin-api.md).

A configuração reaproveita `ConfigEmpresa` do CLI (mesmas faixas e mensagens, SC-009). Segredos usam
`SecretStr`: nunca aparecem em `repr`, log nem mensagem de erro.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from core.tenancy.conexoes import TAMANHO_MINIMO_SEGREDO
from db.config_planos import PLANOS

SLUG_RE: Final = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
Slug = Annotated[str, Field(min_length=3, max_length=63, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
Plano = Literal["recepcionista", "recepcionista_agendador", "pacote_completo"]
EstadoDestino = Literal["ativo", "suspenso", "encerrado"]
FECHADO: Final = "fechado"

assert set(PLANOS) == set(Plano.__args__)  # type: ignore[attr-defined]  # o Literal acompanha db/config_planos


def normalizar_configuracao(config: dict[str, Any]) -> dict[str, Any]:
    """Traduz "fechado" (dia sem atendimento) para a ausência da chave em `horario_funcionamento`."""
    saida = dict(config)
    horario = saida.get("horario_funcionamento")
    if isinstance(horario, dict):
        saida["horario_funcionamento"] = {
            dia: faixa
            for dia, faixa in horario.items()
            if not (isinstance(faixa, str) and faixa.strip().lower() == FECHADO)
        }
    return saida


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConexaoEntrada(_Base):
    instancia: Annotated[str, Field(min_length=1, max_length=100)]
    segredo_entrega: SecretStr
    chave_envio: SecretStr

    @field_validator("segredo_entrega")
    @classmethod
    def _segredo_forte(cls, valor: SecretStr) -> SecretStr:
        if len(valor.get_secret_value()) < TAMANHO_MINIMO_SEGREDO:
            raise ValueError(
                f"O segredo de entrega precisa ter pelo menos {TAMANHO_MINIMO_SEGREDO} caracteres."
            )
        return valor

    @field_validator("chave_envio")
    @classmethod
    def _chave_nao_vazia(cls, valor: SecretStr) -> SecretStr:
        if not valor.get_secret_value():
            raise ValueError("A chave de envio está vazia.")
        return valor


class CriarEmpresa(_Base):
    nome: Annotated[str, Field(min_length=2, max_length=255)]
    slug: Slug
    nicho: Annotated[str, Field(min_length=1, max_length=100)]
    plano: Plano = "recepcionista"
    configuracao: dict[str, Any] = Field(default_factory=dict)
    conexao: ConexaoEntrada | None = None


class EditarEmpresa(_Base):
    versao: Annotated[int, Field(ge=1)]
    slug: str | None = None  # aceito só para recusar mudança (o slug não muda depois de criado)
    nome: Annotated[str, Field(min_length=2, max_length=255)] | None = None
    nicho: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    plano: Plano | None = None
    configuracao: dict[str, Any] = Field(default_factory=dict)


class SubstituirConexao(ConexaoEntrada):
    versao: Annotated[int, Field(ge=1)]


class MudarEstado(_Base):
    versao: Annotated[int, Field(ge=1)]
    para: EstadoDestino
    motivo: Annotated[str, Field(max_length=500)] | None = None
    confirmacao: Annotated[str, Field(max_length=255)] | None = None


class ArquivoEntrada(_Base):
    nome: Annotated[str, Field(min_length=1, max_length=255)]
    conteudo_base64: Annotated[str, Field(max_length=2_900_000)]  # 2 MB em base64 cabe com folga


class EnviarDocumentos(_Base):
    arquivos: Annotated[list[ArquivoEntrada], Field(min_length=1, max_length=10)]


class ConfirmarApagamento(_Base):
    confirmacao: Annotated[str, Field(min_length=1, max_length=255)]
