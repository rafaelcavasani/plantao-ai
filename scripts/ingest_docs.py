"""CLI de ingestão de conhecimento (contrato: contracts/knowledge-cli.md).

    python -m scripts.ingest_docs load <arquivo-ou-pasta>
    python -m scripts.ingest_docs list
    python -m scripts.ingest_docs remove <nome_origem> [--yes]

O tenant é sempre `PILOT_TENANT_ID`. Nenhum conteúdo de arquivo é impresso, só nome, contagens e custo.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from core.config import settings
from core.llm.ports import LLMClient
from core.rag.ingest import (
    STATUS_DE_FALHA,
    ResultadoIngestao,
    ingerir_documento,
    listar_documentos,
    remover_documento,
)


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


async def _carregar(llm: LLMClient, caminho: Path) -> int:
    if not await asyncio.to_thread(caminho.exists):
        print(f"Caminho não encontrado: {caminho}", file=sys.stderr)
        return 1
    tenant_id = settings.tenant_piloto()
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


async def _listar() -> int:
    print(f"{'nome_origem':<24}{'versao':>6}{'trechos':>9}  atualizado_em")
    for d in await listar_documentos(settings.tenant_piloto()):
        print(
            f"{d.nome_origem:<24}{d.versao:>6}{d.num_trechos:>9}  {d.atualizado_em.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )
    return 0


async def _remover(nome: str, confirmado: bool) -> int:
    if not confirmado:
        resposta = await asyncio.to_thread(
            input, f"Remover '{nome}' e todos os seus trechos? [s/N] "
        )
        if resposta.strip().lower() != "s":
            print("Cancelado.")
            return 1
    if await remover_documento(settings.tenant_piloto(), nome):
        print(f"{nome}  REMOVIDO")
        return 0
    print(f"{nome}  NAO_ENCONTRADO")
    return 1


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ingest_docs", description="Carrega a base de conhecimento do tenant piloto."
    )
    sub = p.add_subparsers(dest="comando", required=True)
    carregar = sub.add_parser("load", help="carrega um arquivo ou todos os arquivos de uma pasta")
    carregar.add_argument("caminho", type=Path)
    sub.add_parser("list", help="lista os documentos")
    remover = sub.add_parser("remove", help="remove um documento")
    remover.add_argument("nome_origem")
    remover.add_argument("--yes", action="store_true", help="não pede confirmação")
    return p


async def principal(argv: Sequence[str], llm: LLMClient | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.comando == "list":
        return await _listar()
    if args.comando == "remove":
        return await _remover(args.nome_origem, args.yes)
    if llm is not None:
        return await _carregar(llm, args.caminho)
    from apps.composition import (
        build_llm_client,  # import tardio: a CLI de list/remove não precisa de chave
    )

    cliente = build_llm_client()
    try:
        return await _carregar(cliente, args.caminho)
    finally:
        await cliente.aclose()  # type: ignore[attr-defined]


def main() -> None:
    sys.exit(asyncio.run(principal(sys.argv[1:])))


if __name__ == "__main__":
    main()
