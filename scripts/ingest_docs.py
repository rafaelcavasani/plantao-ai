"""CLI de ingestão de conhecimento (contrato: contracts/knowledge-cli.md e tenants-cli.md).

    python -m scripts.ingest_docs load --tenant SLUG <arquivo-ou-pasta>
    python -m scripts.ingest_docs list --tenant SLUG
    python -m scripts.ingest_docs remove --tenant SLUG <nome_origem> [--yes]

`--tenant` (o `slug` da empresa) é obrigatório: não existe empresa padrão (FR-021). Empresa encerrada é
recusada. Nenhum conteúdo de arquivo é impresso, só nome, contagens e custo.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

from core.llm.ports import LLMClient
from core.rag.ingest import (
    STATUS_DE_FALHA,
    ResultadoIngestao,
    ingerir_documento,
    listar_documentos,
    remover_documento,
)
from core.tenancy import EmpresaNaoEncontrada, Estado, obter_por_slug
from db.admin import admin_session, fechar_admin_engine
from db.session import fechar_engine


class EmpresaEncerrada(Exception):
    """Documentos de empresa encerrada não podem mudar."""


async def _resolver(slug: str) -> uuid.UUID:
    """`slug` -> id da empresa, com o papel administrativo."""
    async with admin_session() as s:
        empresa = await obter_por_slug(s, slug)
        if empresa.status == Estado.ENCERRADO.value:
            raise EmpresaEncerrada(f"A empresa '{slug}' esta encerrada.")
        return empresa.id


def _linha(r: ResultadoIngestao) -> str:
    if r.status == "ok":
        return (
            f"{r.nome}  OK  versao={r.versao}  trechos={r.trechos}  "
            f"tokens_embedding={r.tokens_embedding}  custo_usd={r.custo_usd:f}"
        )
    extra = f"  erro={r.erro}" if r.erro else (f"  versao={r.versao}" if r.versao else "")
    return f"{r.nome}  {r.status.upper()}{extra}"


def _arquivos(caminho: Path) -> list[Path]:
    return sorted(p for p in caminho.iterdir() if p.is_file()) if caminho.is_dir() else [caminho]


async def _carregar(llm: LLMClient, tenant_id: uuid.UUID, caminho: Path) -> int:
    if not await asyncio.to_thread(caminho.exists):
        print(f"Caminho não encontrado: {caminho}", file=sys.stderr)
        return 1
    codigo = 0
    for arquivo in await asyncio.to_thread(_arquivos, caminho):
        resultado = await ingerir_documento(
            llm,
            tenant_id=tenant_id,
            nome_origem=arquivo.name,
            conteudo=await asyncio.to_thread(arquivo.read_bytes),
        )
        print(_linha(resultado))
        if resultado.status in STATUS_DE_FALHA:
            codigo = 1
    return codigo


async def _listar(tenant_id: uuid.UUID) -> int:
    print(f"{'nome_origem':<24}{'versao':>6}{'trechos':>9}  atualizado_em")
    for d in await listar_documentos(tenant_id):
        print(
            f"{d.nome_origem:<24}{d.versao:>6}{d.num_trechos:>9}  {d.atualizado_em.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )
    return 0


async def _remover(tenant_id: uuid.UUID, nome: str, confirmado: bool) -> int:
    if not confirmado:
        resposta = await asyncio.to_thread(
            input, f"Remover '{nome}' e todos os seus trechos? [s/N] "
        )
        if resposta.strip().lower() != "s":
            print("Cancelado.")
            return 1
    if await remover_documento(tenant_id, nome):
        print(f"{nome}  REMOVIDO")
        return 0
    print(f"{nome}  NAO_ENCONTRADO")
    return 1


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ingest_docs", description="Carrega a base de conhecimento de uma empresa."
    )
    sub = p.add_subparsers(dest="comando", required=True)

    def com_empresa(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument("--tenant", required=True, metavar="SLUG", help="slug da empresa")
        return parser

    carregar = com_empresa(
        sub.add_parser("load", help="carrega um arquivo ou todos os arquivos de uma pasta")
    )
    carregar.add_argument("caminho", type=Path)
    com_empresa(sub.add_parser("list", help="lista os documentos"))
    remover = com_empresa(sub.add_parser("remove", help="remove um documento"))
    remover.add_argument("nome_origem")
    remover.add_argument("--yes", action="store_true", help="não pede confirmação")
    return p


async def principal(argv: Sequence[str], llm: LLMClient | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        tenant_id = await _resolver(args.tenant)
    except (EmpresaNaoEncontrada, EmpresaEncerrada) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.comando == "list":
        return await _listar(tenant_id)
    if args.comando == "remove":
        return await _remover(tenant_id, args.nome_origem, args.yes)
    if llm is not None:
        return await _carregar(llm, tenant_id, args.caminho)
    from apps.composition import (
        build_llm_client,  # import tardio: a CLI de list/remove não precisa de chave
    )

    cliente = build_llm_client()
    try:
        return await _carregar(cliente, tenant_id, args.caminho)
    finally:
        await cliente.aclose()  # type: ignore[attr-defined]


async def _executar(argv: Sequence[str]) -> int:
    try:
        return await principal(argv)
    finally:
        await fechar_admin_engine()
        await fechar_engine()


def main() -> None:
    sys.exit(asyncio.run(_executar(sys.argv[1:])))


if __name__ == "__main__":
    main()
