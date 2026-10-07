"""Tipos comuns e erro padrão da API de operação (contrato: specs/004-admin-dashboard/contracts/admin-api.md).

Toda resposta de erro segue `{"codigo", "mensagem", "campos"?}`. Nenhuma mensagem repete valor de campo
secreto: o tratador de validação usa só o texto do erro, nunca o valor recebido.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

Papel = Literal["leitura", "operacao"]
Periodo = Literal["hoje", "7d", "30d"]

DIAS_DO_PERIODO: dict[str, int] = {"hoje": 1, "7d": 7, "30d": 30}


@dataclass(frozen=True)
class Operador:
    """Quem está usando o painel: o e-mail vai para `audit_log.operador`."""

    email: str
    papel: Papel
    expira_em: float = 0.0  # instante (epoch) em que a sessão expira por inatividade

    @property
    def pode_operar(self) -> bool:
        return self.papel == "operacao"


class ErroAdmin(Exception):
    """Erro de negócio da API de operação, convertido em JSON pelo tratador registrado."""

    def __init__(
        self,
        status: int,
        codigo: str,
        mensagem: str,
        *,
        campos: dict[str, str] | None = None,
        extras: dict[str, Any] | None = None,
        cabecalhos: dict[str, str] | None = None,
    ) -> None:
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo
        self.mensagem = mensagem
        self.campos = campos
        self.extras = extras or {}
        self.cabecalhos = cabecalhos or {}

    def corpo(self) -> dict[str, Any]:
        corpo: dict[str, Any] = {"codigo": self.codigo, "mensagem": self.mensagem}
        if self.campos is not None:
            corpo["campos"] = self.campos
        corpo.update(self.extras)
        return corpo


_TRADUCOES = {
    "missing": "Campo obrigatório.",
    "string_too_short": "Texto curto demais.",
    "string_too_long": "Texto longo demais.",
    "string_pattern_mismatch": "Formato inválido.",
    "greater_than_equal": "Valor abaixo do mínimo permitido.",
    "less_than_equal": "Valor acima do máximo permitido.",
    "int_parsing": "Informe um número inteiro.",
    "float_parsing": "Informe um número.",
    "literal_error": "Valor não permitido.",
    "enum": "Valor não permitido.",
    "extra_forbidden": "Campo desconhecido.",
}


def campos_da_validacao(erros: list[Any]) -> dict[str, str]:
    """Um item `campo: motivo` por campo inválido, sem nunca repetir o valor recebido."""
    campos: dict[str, str] = {}
    for erro in erros:
        caminho = [str(p) for p in erro.get("loc", ()) if p not in ("body", "query", "path")]
        campo = ".".join(caminho) or "corpo"
        motivo = _TRADUCOES.get(str(erro.get("type")), None)
        if motivo is None:
            motivo = str(erro.get("msg", "Valor inválido.")).removeprefix("Value error, ")
        campos.setdefault(campo, motivo)
    return campos


def registrar_erros(app: FastAPI) -> None:
    """Instala os tratadores de `ErroAdmin` e de validação (sempre em português e sem valores)."""

    @app.exception_handler(ErroAdmin)
    async def _erro_admin(_: Request, exc: ErroAdmin) -> JSONResponse:
        return JSONResponse(exc.corpo(), status_code=exc.status, headers=exc.cabecalhos)

    @app.exception_handler(RequestValidationError)
    async def _validacao(request: Request, exc: RequestValidationError) -> Response:
        if not request.url.path.startswith("/admin"):
            return await request_validation_exception_handler(request, exc)
        corpo = {
            "codigo": "validacao",
            "mensagem": "Corrija os campos indicados.",
            "campos": campos_da_validacao(list(exc.errors())),
        }
        return JSONResponse(corpo, status_code=400)
