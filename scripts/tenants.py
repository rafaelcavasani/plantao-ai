"""CLI do operador para empresas (contrato: specs/002-multitenancy/contracts/tenants-cli.md).

    python -m scripts.tenants create --file empresa.yml --operador NOME
    python -m scripts.tenants list | status SLUG
    python -m scripts.tenants readiness SLUG --operador NOME
    python -m scripts.tenants test SLUG --file empresa.yml --operador NOME
    python -m scripts.tenants activate SLUG --operador NOME
    python -m scripts.tenants suspend SLUG --operador NOME [--motivo TEXTO]
    python -m scripts.tenants resume SLUG --operador NOME
    python -m scripts.tenants close SLUG --operador NOME [--motivo TEXTO]
    python -m scripts.tenants purge SLUG --operador NOME --confirmar "NOME DA EMPRESA"    python -m scripts.tenants config show SLUG
    python -m scripts.tenants config set SLUG --operador NOME campo=valor [campo=valor ...]
    python -m scripts.tenants audit SLUG [--limite N]

Usa o papel administrativo (`DATABASE_ADMIN_URL`) para operar entre empresas e `tenant_session` para dados de
uma empresa. Nenhuma saída traz credencial, telefone ou texto de cliente final (FR-005).
Código de saída: 0 sucesso; 1 operação recusada ou falha externa; 2 uso incorreto ou arquivo inválido.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Final

from redis.asyncio import Redis
from sqlalchemy import func, select

from agents.orchestrator.graph import Grafo
from agents.orchestrator.state import ConfigTenant, EntradaMensagem
from core.llm.ports import LLMClient, LLMError, SaidaInvalida
from core.ports.channel import MessageChannel
from core.tenancy import (
    ConexaoEmUso,
    EmpresaNaoEncontrada,
    ExclusaoRecusada,
    TransicaoInvalida,
    apagar_dados,
    encerrar,
    listar,
    obter_por_slug,
    retomar,
    suspender,
)
from core.tenancy.config import (
    ConfigInvalida,
    aplicar_alteracoes,
    interpretar_atribuicoes,
    valores_da_config,
)
from core.tenancy.onboarding import (
    ArquivoInvalido,
    OnboardingRecusado,
    ResultadoCriacao,
    carregar_arquivo,
    carregar_teste,
    criar_ou_continuar,
)
from core.tenancy.prontidao import (
    Prontidao,
    ativar,
    avaliar_prontidao,
    avaliar_resposta_teste,
    registrar_teste,
)
from db.admin import admin_session, fechar_admin_engine
from db.models import (
    AuditLog,
    ChannelConnection,
    KnowledgeDocument,
    ReadinessCheck,
    TenantConfig,
)
from db.repositories import carregar_config
from db.session import fechar_engine, tenant_session


def _data(valor: datetime | None) -> str:
    return valor.strftime("%Y-%m-%dT%H:%M:%SZ") if valor else "-"


def _segundos(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",")


def _valor(valor: object, limite: int | None = None) -> str:
    """Valor em JSON legível; `-` para ausente; cortado em `limite` caracteres."""
    if valor is None:
        return "-"
    texto = json.dumps(valor, ensure_ascii=False)
    return texto if limite is None or len(texto) <= limite else texto[: limite - 1] + "…"


def _imprimir_criacao(r: ResultadoCriacao, total: float) -> None:
    print(f"Empresa: {r.slug} ({r.estado})            [{'novo' if r.novo else 'existente'}]")
    for i, passo in enumerate(r.passos, start=1):
        situacao = "OK" if passo.ok else "FALHA"
        print(
            f"  [{i}/{len(r.passos)}] {passo.nome:<15} {situacao:<9}{_segundos(passo.segundos):>5} s"
            f"   {passo.detalhe}".rstrip()
        )
    for d in r.documentos:
        if d.status not in ("ok", "inalterado"):
            extra = f"  erro={d.erro}" if d.erro else ""
            print(f"      documento {d.nome}  {d.status.upper()}{extra}")
    print(f"Total: {_segundos(total)} s. Proximo passo: readiness {r.slug}")


def _imprimir_prontidao(slug: str, p: Prontidao) -> None:
    print(f"Prontidao de {slug}")
    for item in p.itens:
        print(f"  {item.nome:<26}{'OK' if item.ok else 'FALTA':<6}{item.detalhe}".rstrip())
    if p.aprovada:
        print("Resultado: APROVADA")
    else:
        n = len(p.pendencias)
        print(f"Resultado: REPROVADA ({n} {'pendencia' if n == 1 else 'pendencias'})")


async def _criar(args: argparse.Namespace, llm: LLMClient | None) -> int:
    try:
        arquivo = carregar_arquivo(Path(args.file))
    except ArquivoInvalido as exc:
        print("Arquivo invalido:", file=sys.stderr)
        for erro in exc.erros:
            print(f"  {erro}", file=sys.stderr)
        return 2
    cliente = llm
    proprio = False
    if cliente is None and arquivo.documentos is not None:
        from apps.composition import (
            build_llm_client,
        )  # import tardio: só quem indexa precisa da chave

        cliente, proprio = build_llm_client(), True
    inicio = asyncio.get_running_loop().time()
    try:
        resultado = await criar_ou_continuar(
            arquivo, operador=args.operador, llm=cliente, sessao_admin=admin_session
        )
    except (ConexaoEmUso, OnboardingRecusado) as exc:
        print(f"Recusado: {exc}", file=sys.stderr)
        return 1
    finally:
        if proprio and cliente is not None:
            await cliente.aclose()  # type: ignore[attr-defined]
    _imprimir_criacao(resultado, asyncio.get_running_loop().time() - inicio)
    return 1 if resultado.falhou else 0


async def _listar() -> int:
    async with admin_session() as s:
        empresas = await listar(s)
        conexoes = {c.tenant_id: c for c in (await s.execute(select(ChannelConnection))).scalars()}
    print(f"{'slug':<28}{'estado':<16}{'ativada_em':<22}{'instancia':<24}verificada_em")
    for e in empresas:
        c = conexoes.get(e.id)
        print(
            f"{e.slug:<28}{e.status:<16}{_data(e.ativado_em):<22}"
            f"{(c.instance_name if c else '-'):<24}{_data(c.verificada_em if c else None)}"
        )
    return 0


async def _status(slug: str) -> int:
    async with admin_session() as s:
        e = await obter_por_slug(s, slug)
        docs, trechos = (
            await s.execute(
                select(
                    func.count(), func.coalesce(func.sum(KnowledgeDocument.num_trechos), 0)
                ).where(KnowledgeDocument.tenant_id == e.id)
            )
        ).one()
        conexao = (
            await s.execute(select(ChannelConnection).where(ChannelConnection.tenant_id == e.id))
        ).scalar_one_or_none()
        ultimas = {
            tipo: (
                await s.execute(
                    select(ReadinessCheck)
                    .where(ReadinessCheck.tenant_id == e.id, ReadinessCheck.tipo == tipo)
                    .order_by(ReadinessCheck.executado_em.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            for tipo in ("prontidao", "conversa_teste")
        }
    print(f"Empresa: {e.slug}  {e.nome_empresa}  nicho={e.nicho}  plano={e.plano}")
    print(
        f"Estado: {e.status}  criada={_data(e.criado_em)}  ativada={_data(e.ativado_em)}  "
        f"encerrada={_data(e.encerrado_em)}  dados_apagados={_data(e.dados_apagados_em)}"
    )
    print(f"Documentos: {docs}  trechos: {trechos}")
    if conexao is None:
        print("Conexao: nenhuma")
    else:
        print(
            f"Conexao: {conexao.canal}/{conexao.provedor}  instancia={conexao.instance_name}  "
            f"verificada_em={_data(conexao.verificada_em)}"
        )
    for rotulo, tipo in (("Ultima prontidao", "prontidao"), ("Ultimo teste", "conversa_teste")):
        linha = ultimas[tipo]
        if linha is None:
            print(f"{rotulo}: nenhuma")
        else:
            print(
                f"{rotulo}: {'APROVADA' if linha.aprovado else 'REPROVADA'} em "
                f"{_data(linha.executado_em)} por {linha.operador}"
            )
    return 0


async def _prontidao(slug: str, operador: str, channel: MessageChannel) -> int:
    async with admin_session() as s:
        empresa = await obter_por_slug(s, slug)
        resultado = await avaliar_prontidao(s, empresa.id, channel, operador)
    _imprimir_prontidao(slug, resultado)
    return 0 if resultado.aprovada else 1


async def _ativar(slug: str, operador: str, channel: MessageChannel) -> int:
    async with admin_session() as s:
        empresa = await obter_por_slug(s, slug)
        try:
            resultado = await ativar(s, empresa.id, channel, operador)
        except TransicaoInvalida as exc:
            print(str(exc), file=sys.stderr)
            return 1
    _imprimir_prontidao(slug, resultado)
    if resultado.aprovada:
        print(f"Empresa {slug} ativada.")
        return 0
    print("Ativacao recusada.")
    return 1


async def _suspender(slug: str, operador: str, motivo: str | None) -> int:
    async with admin_session() as s:
        empresa = await obter_por_slug(s, slug)
        try:
            await suspender(s, empresa.id, operador, motivo=motivo)
        except TransicaoInvalida as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(f"Empresa {slug} suspensa. Mensagens novas ficam guardadas e nao sao respondidas.")
    return 0


async def _retomar(slug: str, operador: str) -> int:
    async with admin_session() as s:
        empresa = await obter_por_slug(s, slug)
        try:
            await retomar(s, empresa.id, operador)
        except TransicaoInvalida as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(f"Empresa {slug} reativada. As mensagens guardadas na suspensao nao sao reprocessadas.")
    return 0


async def _encerrar(slug: str, operador: str, motivo: str | None) -> int:
    async with admin_session() as s:
        empresa = await obter_por_slug(s, slug)
        try:
            await encerrar(s, empresa.id, operador, motivo=motivo)
        except TransicaoInvalida as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(
        f"Empresa {slug} encerrada. Nenhuma resposta sera enviada e o numero continua reservado. "
        f'Para apagar os dados: purge {slug} --confirmar "NOME DA EMPRESA".'
    )
    return 0


def _tempo(segundos: float) -> str:
    return f"{int(segundos)} s" if segundos < 60 else f"{int(segundos // 60)} min"


# Ordem de leitura da saída de `purge` (contracts/tenants-cli.md), independente da ordem de exclusão.
_ORDEM_DA_SAIDA: Final = (
    "conversas",
    "mensagens",
    "documentos",
    "trechos",
    "usos",
    "repasses",
    "agendamentos",
    "leads",
    "cobrancas",
    "metricas",
    "painel_horas",
    "painel_situacao",
    "prontidoes",
    "credenciais",
    "conexoes",
    "configuracao",
)


async def _apagar(slug: str, operador: str, confirmacao: str, redis: Redis | None) -> int:
    async with admin_session() as s:
        empresa = await obter_por_slug(s, slug)
        tenant_id = empresa.id
    cliente, proprio = redis, False
    if cliente is None:
        from core.config import settings

        cliente, proprio = Redis.from_url(settings.redis_url), True
    try:
        resultado = await apagar_dados(
            admin_session, tenant_id, confirmacao, operador, redis=cliente
        )
    except ExclusaoRecusada as exc:
        print(f"Recusado: {exc}", file=sys.stderr)
        return 1
    finally:
        if proprio and cliente is not None:
            await cliente.aclose()
    print(
        f"Empresa encerrada ha {_tempo(resultado.encerrada_ha_segundos)} "
        f"(drenagem de {resultado.drenagem_segundos} s cumprida)."
    )
    print("Apagado: " + " ".join(f"{k}={resultado.contagens[k]}" for k in _ORDEM_DA_SAIDA))
    print(f"Numero (instancia {resultado.instance_name or '-'}) liberado. Auditoria registrada.")
    return 0


async def _config_mostrar(slug: str) -> int:
    async with admin_session() as s:
        empresa = await obter_por_slug(s, slug)
        linha = await s.get(TenantConfig, empresa.id)
    if linha is None:
        print(f"Empresa {slug} sem configuracao.", file=sys.stderr)
        return 1
    print(f"Configuracao de {slug}")
    for campo, valor in valores_da_config(linha).items():
        print(f"  {campo:<30}{_valor(valor)}")
    return 0


async def _config_alterar(slug: str, operador: str, pares: Sequence[str]) -> int:
    try:
        alteracoes = interpretar_atribuicoes(pares)
    except ConfigInvalida as exc:
        print("Uso incorreto:", file=sys.stderr)
        for erro in exc.erros:
            print(f"  {erro}", file=sys.stderr)
        return 2
    async with admin_session() as s:
        empresa = await obter_por_slug(s, slug)
        try:
            alterados = await aplicar_alteracoes(s, empresa.id, alteracoes, operador)
        except ConfigInvalida as exc:
            print("Configuracao invalida; nada foi alterado:", file=sys.stderr)
            for erro in exc.erros:
                print(f"  {erro}", file=sys.stderr)
            return 1
    if alterados:
        print(
            f"Configuracao de {slug}: {len(alterados)} campo(s) alterado(s): {', '.join(alterados)}"
        )
    else:
        print(f"Configuracao de {slug}: nenhuma alteracao (valores ja eram esses).")
    return 0


async def _auditar(slug: str, limite: int) -> int:
    async with admin_session() as s:
        empresa = await obter_por_slug(s, slug)
        linhas = (
            (
                await s.execute(
                    select(AuditLog)
                    .where(AuditLog.tenant_id == empresa.id)
                    .order_by(AuditLog.criado_em.desc(), AuditLog.id.desc())
                    .limit(limite)
                )
            )
            .scalars()
            .all()
        )
    print(f"Auditoria de {slug} (ultimas {len(linhas)})")
    print(f"{'data':<22}{'campo':<34}{'anterior':<26}{'novo':<26}operador")
    for r in linhas:
        print(
            f"{_data(r.criado_em):<22}{r.entidade + '.' + r.campo:<34}"
            f"{_valor(r.valor_anterior, 24):<26}{_valor(r.valor_novo, 24):<26}{r.operador}"
        )
    return 0


async def _testar(args: argparse.Namespace, llm: LLMClient | None) -> int:
    try:
        slug_arquivo, teste = carregar_teste(Path(args.file))
    except ArquivoInvalido as exc:
        for erro in exc.erros:
            print(erro, file=sys.stderr)
        return 2
    if slug_arquivo != args.slug:
        print("slug: o arquivo e de outra empresa", file=sys.stderr)
        return 2
    async with admin_session() as s:
        empresa = await obter_por_slug(s, args.slug)
        tenant_id = empresa.id
    cliente, proprio = llm, False
    if cliente is None:
        from apps.composition import build_llm_client

        cliente, proprio = build_llm_client(), True
    detalhes: dict[str, object]
    try:
        async with tenant_session(tenant_id) as s:
            config = ConfigTenant.de_modelo(await carregar_config(s, tenant_id))
        try:
            decisao = await Grafo(cliente).executar(
                EntradaMensagem(tenant_id, None, None, teste.pergunta, "texto"), config
            )
            aprovado = avaliar_resposta_teste(decisao.acao, decisao.texto, teste.esperado)
            detalhes = {
                "acao": decisao.acao,
                "motivo": decisao.motivo,
                "termos": len(teste.esperado),
            }
        except (LLMError, SaidaInvalida) as exc:
            aprovado = False
            detalhes = {"acao": "erro", "motivo": type(exc).__name__, "termos": len(teste.esperado)}
    finally:
        if proprio:
            await cliente.aclose()  # type: ignore[attr-defined]
    async with admin_session() as s:
        await registrar_teste(s, tenant_id, args.operador, aprovado, detalhes)
    motivo = f" ({detalhes['acao']}: {detalhes['motivo']})" if not aprovado else ""
    print(f"Conversa de teste de {args.slug}: {'APROVADA' if aprovado else 'REPROVADA'}{motivo}")
    return 0 if aprovado else 1


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tenants", description="Operação de empresas (multi-tenancy).")
    sub = p.add_subparsers(dest="comando", required=True)

    def com_operador(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument("--operador", required=True, help="quem executa; vai para a auditoria")
        return parser

    criar = com_operador(sub.add_parser("create", help="cria a empresa ou continua de onde parou"))
    criar.add_argument("--file", required=True)
    sub.add_parser("list", help="lista as empresas")
    status = sub.add_parser("status", help="situação de uma empresa")
    status.add_argument("slug")
    pronta = com_operador(sub.add_parser("readiness", help="avalia os itens de prontidão"))
    pronta.add_argument("slug")
    teste = com_operador(sub.add_parser("test", help="executa a conversa simulada do arquivo"))
    teste.add_argument("slug")
    config = sub.add_parser("config", help="mostra ou altera a configuração da empresa")
    acoes = config.add_subparsers(dest="acao_config", required=True)
    mostrar = acoes.add_parser("show", help="valores atuais")
    mostrar.add_argument("slug")
    alterar = com_operador(
        acoes.add_parser("set", help="altera campos (campo=valor, valor em JSON)")
    )
    alterar.add_argument("slug")
    alterar.add_argument("pares", nargs="+", metavar="campo=valor")
    auditoria = sub.add_parser("audit", help="últimas linhas de auditoria da empresa")
    auditoria.add_argument("slug")
    auditoria.add_argument("--limite", type=int, default=20, help="quantas linhas (padrão 20)")
    teste.add_argument("--file", required=True, help="arquivo com `teste_prontidao`")
    ativa = com_operador(sub.add_parser("activate", help="ativa se a prontidão estiver aprovada"))
    ativa.add_argument("slug")
    suspende = com_operador(sub.add_parser("suspend", help="suspende uma empresa ativa"))
    suspende.add_argument("slug")
    suspende.add_argument("--motivo", help="vai para a auditoria")
    retoma = com_operador(sub.add_parser("resume", help="reativa uma empresa suspensa"))
    retoma.add_argument("slug")
    encerra = com_operador(
        sub.add_parser("close", help="encerra a empresa (numero fica reservado)")
    )
    encerra.add_argument("slug")
    encerra.add_argument("--motivo", help="vai para a auditoria")
    apaga = com_operador(sub.add_parser("purge", help="apaga os dados de uma empresa encerrada"))
    apaga.add_argument("slug")
    apaga.add_argument("--confirmar", required=True, metavar="NOME", help="nome exato da empresa")
    return p


async def principal(
    argv: Sequence[str],
    llm: LLMClient | None = None,
    channel: MessageChannel | None = None,
    redis: Redis | None = None,
) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        if args.comando == "create":
            return await _criar(args, llm)
        if args.comando == "config":
            if args.acao_config == "show":
                return await _config_mostrar(args.slug)
            return await _config_alterar(args.slug, args.operador, args.pares)
        if args.comando == "audit":
            if args.limite < 1:
                print("--limite deve ser pelo menos 1", file=sys.stderr)
                return 2
            return await _auditar(args.slug, args.limite)
        if args.comando == "list":
            return await _listar()
        if args.comando == "status":
            return await _status(args.slug)
        if args.comando == "test":
            return await _testar(args, llm)
        if args.comando == "suspend":
            return await _suspender(args.slug, args.operador, args.motivo)
        if args.comando == "resume":
            return await _retomar(args.slug, args.operador)
        if args.comando == "close":
            return await _encerrar(args.slug, args.operador, args.motivo)
        if args.comando == "purge":
            return await _apagar(args.slug, args.operador, args.confirmar, redis)
        canal, proprio = channel, False
        if canal is None:
            from apps.composition import build_channel

            canal, proprio = build_channel(), True
        try:
            if args.comando == "readiness":
                return await _prontidao(args.slug, args.operador, canal)
            return await _ativar(args.slug, args.operador, canal)
        finally:
            if proprio:
                await canal.aclose()  # type: ignore[attr-defined]
    except EmpresaNaoEncontrada as exc:
        print(str(exc), file=sys.stderr)
        return 1


async def _executar(argv: Sequence[str]) -> int:
    try:
        return await principal(argv)
    finally:
        await fechar_admin_engine()
        await fechar_engine()


def main() -> None:
    from core.config import settings

    settings.exigir_segredos()
    sys.exit(asyncio.run(_executar(sys.argv[1:])))


if __name__ == "__main__":
    main()
