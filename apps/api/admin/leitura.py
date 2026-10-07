"""Rotas de leitura do painel (`GET /admin/*`). Exigem sessão válida; qualquer papel lê.

Só usam `core.painel.consultas`, que lê pelo papel `plantao_painel` (sem conteúdo de mensagem, contato nem
credenciais). Este módulo NÃO importa `db.admin` (contrato do import-linter).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import JSONResponse, Response

from apps.api.admin.auth import operador_atual
from apps.api.admin.schemas import ErroAdmin, Periodo
from core.painel import consultas, conversas, ficha, planos
from core.painel.consultas import FiltrosLista

router = APIRouter(dependencies=[Depends(operador_atual)])


@router.get("/saude", response_model=None)
async def saude() -> Any:
    """Idade dos números. Passou de 10 minutos: 503 `dados_desatualizados` (para monitoramento externo)."""
    corpo = await consultas.saude_dos_dados()
    if corpo["desatualizado"]:
        return JSONResponse(
            {
                "codigo": "dados_desatualizados",
                "mensagem": "Os números do painel estão desatualizados.",
                **corpo,
            },
            status_code=503,
        )
    return corpo


Ordem = Literal[
    "nome",
    "estado",
    "mensagens",
    "abertas",
    "handoffs",
    "ultima_mensagem",
    "custo",
    "orcamento",
    "criada_em",
]
Estado = Literal["ativo", "em_configuracao", "suspenso", "encerrado"]


def _filtros(
    periodo: Annotated[Periodo, Query()] = "30d",
    q: Annotated[str | None, Query(max_length=100)] = None,
    estado: Annotated[Estado | None, Query()] = None,
    nicho: Annotated[str | None, Query(max_length=100)] = None,
    ordem: Annotated[Ordem, Query()] = "nome",
    sentido: Annotated[Literal["asc", "desc"], Query()] = "asc",
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamanho: Annotated[int, Query(ge=1, le=100)] = 25,
) -> FiltrosLista:
    return FiltrosLista(periodo, q, estado, nicho, ordem, sentido, pagina, tamanho)


Filtros = Annotated[FiltrosLista, Depends(_filtros)]


@router.get("/visao-geral")
async def visao_geral(periodo: Annotated[Periodo, Query()] = "30d") -> dict[str, Any]:
    return await consultas.visao_geral(periodo)


@router.get("/empresas")
async def listar_empresas(filtros: Filtros) -> dict[str, Any]:
    return await consultas.listar_empresas(filtros)


@router.get("/empresas.csv")
async def exportar_empresas(filtros: Filtros) -> Response:
    corpo = await consultas.exportar_csv(filtros)
    return Response(
        corpo,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="plantao-empresas.csv"'},
    )


@router.get("/planos")
async def listar_planos() -> list[dict[str, object]]:
    return planos.listar_planos()


Slug = Annotated[str, Path(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=63)]


def nao_encontrada() -> ErroAdmin:
    return ErroAdmin(404, "empresa_nao_encontrada", "Empresa não encontrada.")


@router.get("/empresas/{slug}")
async def ficha_da_empresa(
    slug: Slug, periodo: Annotated[Periodo, Query()] = "30d"
) -> dict[str, Any]:
    try:
        return await ficha.ficha(slug, periodo)
    except ficha.EmpresaInexistente as exc:
        raise nao_encontrada() from exc


@router.get("/empresas/{slug}/serie")
async def serie_da_empresa(
    slug: Slug, periodo: Annotated[Periodo, Query()] = "30d"
) -> dict[str, Any]:
    try:
        return await ficha.serie_da_empresa(slug, periodo)
    except ficha.EmpresaInexistente as exc:
        raise nao_encontrada() from exc


@router.get("/empresas/{slug}/configuracao")
async def configuracao_da_empresa(slug: Slug) -> dict[str, Any]:
    try:
        return await ficha.configuracao(slug)
    except ficha.EmpresaInexistente as exc:
        raise nao_encontrada() from exc


@router.get("/empresas/{slug}/auditoria")
async def auditoria_da_empresa(
    slug: Slug,
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamanho: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    try:
        return await ficha.auditoria(slug, pagina, tamanho)
    except ficha.EmpresaInexistente as exc:
        raise nao_encontrada() from exc


@router.get("/empresas/{slug}/conversas")
async def listar_conversas(
    slug: Slug,
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamanho: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    """Só metadados: nenhum campo de texto nem de contato existe nesta resposta (US5)."""
    try:
        return await conversas.listar_conversas(slug, pagina, tamanho)
    except conversas.EmpresaInexistente as exc:
        raise nao_encontrada() from exc


@router.get("/empresas/{slug}/conversas/{conversa_id}")
async def detalhe_da_conversa(slug: Slug, conversa_id: uuid.UUID) -> dict[str, Any]:
    try:
        return await conversas.conversa(slug, conversa_id)
    except conversas.EmpresaInexistente as exc:
        raise nao_encontrada() from exc
    except conversas.ConversaInexistente as exc:
        raise ErroAdmin(404, "conversa_nao_encontrada", "Conversa não encontrada.") from exc
