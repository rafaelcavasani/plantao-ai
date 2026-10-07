"""Rotas de escrita do painel (`POST/PATCH/PUT /admin/*`). Papel `operacao`, `Origin` e limite de taxa.

ÚNICO módulo de `apps/` autorizado a importar `db.admin` (contrato do import-linter, ADR-0006). Cada rota
abre UMA transação administrativa, confere `tenants.versao` (concorrência otimista, FR-040), chama os mesmos
serviços de `core/tenancy` que o CLI usa e grava a auditoria com o e-mail do operador autenticado.
Segredos entram só aqui e nunca saem em resposta, log nem erro.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from functools import lru_cache
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.auth import OperadorAtual
from apps.api.admin.entradas import (
    ConfirmarApagamento,
    CriarEmpresa,
    EditarEmpresa,
    EnviarDocumentos,
    MudarEstado,
    SubstituirConexao,
    normalizar_configuracao,
)
from apps.api.admin.leitura import Slug, nao_encontrada
from apps.api.admin.schemas import ErroAdmin
from apps.api.admin.seguranca import Escritor
from apps.api.deps import get_queue, get_redis
from apps.composition import build_channel
from core.config import settings
from core.painel import ficha as ficha_do_painel
from core.painel.remessas import PREFIXO_REMESSA, VALIDADE_REMESSA_S
from core.ports.channel import MessageChannel
from core.rag.chunking import EXTENSOES_SUPORTADAS
from core.tenancy.auditoria import registrar_mudanca
from core.tenancy.ciclo_vida import TRANSICOES, Estado, TransicaoInvalida, retomar, suspender
from core.tenancy.conexoes import ConexaoEmUso, SegredoInvalido, cadastrar_conexao
from core.tenancy.config import ConfigInvalida, aplicar_alteracoes, valores_da_config
from core.tenancy.exclusao import (
    ORDEM_DE_EXCLUSAO,
    ExclusaoRecusada,
    apagar_dados,
    encerrar,
)
from core.tenancy.onboarding import OnboardingRecusado, garantir_empresa
from core.tenancy.prontidao import ativar, avaliar_prontidao
from db.admin import admin_session
from db.models import ChannelConnection, Tenant, TenantConfig

router = APIRouter()

TAMANHO_MAXIMO_ARQUIVO: Final = 2 * 1024 * 1024


@lru_cache
def get_canal() -> MessageChannel:
    """Canal usado só para verificar a conexão na prontidão (substituível nos testes)."""
    return build_channel()


Canal = Annotated[MessageChannel, Depends(get_canal)]
RedisDep = Annotated[Redis, Depends(get_redis)]


# --- Apoio --------------------------------------------------------------------------------------


def _campos_de_config(erros: list[str]) -> dict[str, str]:
    """`["campo: motivo", ...]` do serviço de configuração → `{"configuracao.campo": "motivo"}`."""
    campos: dict[str, str] = {}
    for erro in erros:
        campo, _, motivo = erro.partition(": ")
        campos.setdefault(f"configuracao.{campo}" if motivo else "configuracao", motivo or campo)
    return campos


def _erro_de_config(exc: ConfigInvalida) -> ErroAdmin:
    return ErroAdmin(
        400, "validacao", "Corrija os campos indicados.", campos=_campos_de_config(list(exc.erros))
    )


async def _travar(s: AsyncSession, slug: str, versao: int | None) -> Tenant:
    """Empresa pelo `slug`, travada para escrita. `versao` diferente da atual = 409 `conflito_versao`."""
    empresa = (
        await s.execute(select(Tenant).where(Tenant.slug == slug).with_for_update())
    ).scalar_one_or_none()
    if empresa is None:
        raise nao_encontrada()
    if versao is not None and empresa.versao != versao:
        config = await s.get(TenantConfig, empresa.id)
        raise ErroAdmin(
            409,
            "conflito_versao",
            "A empresa foi alterada por outra pessoa desde que você abriu esta tela.",
            extras={
                "atual": {
                    "versao": empresa.versao,
                    "nome": empresa.nome_empresa,
                    "nicho": empresa.nicho,
                    "plano": empresa.plano,
                    "estado": empresa.status,
                    "configuracao": valores_da_config(config) if config else None,
                }
            },
        )
    return empresa


def _permitidos(estado: str) -> list[str]:
    return [d.value for d in TRANSICOES[Estado(estado)]]


async def _resposta(slug: str, **extras: Any) -> dict[str, Any]:
    corpo = await ficha_do_painel.ficha(slug)
    corpo.update(extras)
    return corpo


# --- Criar e editar -----------------------------------------------------------------------------


@router.post("/empresas", status_code=201)
async def criar_empresa(corpo: CriarEmpresa, operador: Escritor) -> dict[str, Any]:
    config = normalizar_configuracao(corpo.configuracao)
    async with admin_session() as s:
        existente = (
            await s.execute(select(Tenant).where(Tenant.slug == corpo.slug).with_for_update())
        ).scalar_one_or_none()
        # Repetir o mesmo cadastro em uma empresa ainda em configuração completa o que falta (como o CLI).
        if existente is not None and not (
            existente.status == Estado.EM_CONFIGURACAO.value
            and existente.nome_empresa == corpo.nome
        ):
            raise ErroAdmin(
                409,
                "slug_em_uso",
                f"Já existe uma empresa com o slug '{corpo.slug}'.",
                campos={"slug": f"Já existe uma empresa com o slug '{corpo.slug}'."},
            )
        antes = (existente.nicho, existente.plano) if existente is not None else None
        conexao_alterada = False
        try:
            tenant_id, nova, _ = await garantir_empresa(
                s,
                slug=corpo.slug,
                nome_empresa=corpo.nome,
                nicho=corpo.nicho,
                plano=corpo.plano,
                instance_name=corpo.conexao.instancia if corpo.conexao else None,
                operador=operador.email,
            )
            alterados = await aplicar_alteracoes(s, tenant_id, config, operador.email)
            if corpo.conexao is not None:
                cadastro = await cadastrar_conexao(
                    s,
                    tenant_id,
                    instance_name=corpo.conexao.instancia,
                    webhook_secret=corpo.conexao.segredo_entrega.get_secret_value(),
                    api_key=corpo.conexao.chave_envio.get_secret_value(),
                    operador=operador.email,
                )
                conexao_alterada = cadastro.alterada
        except ConfigInvalida as exc:
            raise _erro_de_config(exc) from exc
        except ConexaoEmUso as exc:
            raise ErroAdmin(
                409, "instancia_em_uso", str(exc), campos={"conexao.instancia": str(exc)}
            ) from exc
        except SegredoInvalido as exc:
            raise ErroAdmin(
                400,
                "validacao",
                "Corrija os campos indicados.",
                campos={"conexao.segredo_entrega": str(exc)},
            ) from exc
        except OnboardingRecusado as exc:
            raise ErroAdmin(409, "empresa_encerrada", str(exc)) from exc
        empresa = await s.get(Tenant, tenant_id)
        assert empresa is not None
        depois = (empresa.nicho, empresa.plano)
        if not nova and (alterados or conexao_alterada or depois != antes):
            empresa.versao += (
                1  # a empresa nova nasce na versão 1; só a alteração de uma existente conta
            )
    return await _resposta(corpo.slug)


@router.patch("/empresas/{slug}")
async def editar_empresa(slug: Slug, corpo: EditarEmpresa, operador: Escritor) -> dict[str, Any]:
    if corpo.slug is not None and corpo.slug != slug:
        raise ErroAdmin(
            400,
            "validacao",
            "Corrija os campos indicados.",
            campos={"slug": "O slug não pode mudar depois que a empresa é criada."},
        )
    alteracoes = 0
    async with admin_session() as s:
        empresa = await _travar(s, slug, corpo.versao)
        if empresa.status == Estado.ENCERRADO.value:
            raise ErroAdmin(409, "empresa_encerrada", "Empresa encerrada não pode ser editada.")
        for campo, novo in (
            ("nome_empresa", corpo.nome),
            ("nicho", corpo.nicho),
            ("plano", corpo.plano),
        ):
            if novo is not None and getattr(empresa, campo) != novo:
                await registrar_mudanca(
                    s, empresa.id, "config", campo, getattr(empresa, campo), novo, operador.email
                )
                setattr(empresa, campo, novo)
                alteracoes += 1
        try:
            alterados = await aplicar_alteracoes(
                s, empresa.id, normalizar_configuracao(corpo.configuracao), operador.email
            )
        except ConfigInvalida as exc:
            raise _erro_de_config(exc) from exc
        alteracoes += len(alterados)
        if alteracoes:
            empresa.versao += 1
    return await _resposta(slug, alteracoes=alteracoes)


@router.put("/empresas/{slug}/conexao")
async def substituir_conexao(
    slug: Slug, corpo: SubstituirConexao, operador: Escritor
) -> dict[str, Any]:
    async with admin_session() as s:
        empresa = await _travar(s, slug, corpo.versao)
        if empresa.status == Estado.ENCERRADO.value:
            raise ErroAdmin(409, "empresa_encerrada", "Empresa encerrada não pode ser editada.")
        try:
            resultado = await cadastrar_conexao(
                s,
                empresa.id,
                instance_name=corpo.instancia,
                webhook_secret=corpo.segredo_entrega.get_secret_value(),
                api_key=corpo.chave_envio.get_secret_value(),
                operador=operador.email,
            )
        except ConexaoEmUso as exc:
            raise ErroAdmin(
                409, "instancia_em_uso", str(exc), campos={"instancia": str(exc)}
            ) from exc
        if resultado.alterada:
            # Credencial nova exige nova verificação do canal (FR-038).
            conexao = await s.get(ChannelConnection, resultado.connection_id)
            if conexao is not None:
                conexao.verificada_em = None
            empresa.versao += 1
    return await _resposta(slug)


# --- Estado e prontidão -------------------------------------------------------------------------


@router.post("/empresas/{slug}/estado")
async def mudar_estado_da_empresa(
    slug: Slug, corpo: MudarEstado, operador: Escritor, canal: Canal
) -> dict[str, Any]:
    reprovada: list[dict[str, Any]] | None = None
    async with admin_session() as s:
        empresa = await _travar(s, slug, corpo.versao)
        atual = empresa.status
        if corpo.para == "encerrado" and corpo.confirmacao != empresa.nome_empresa:
            raise ErroAdmin(
                400,
                "validacao",
                "Corrija os campos indicados.",
                campos={"confirmacao": "Digite o nome exato da empresa para encerrar."},
            )
        try:
            if corpo.para == "suspenso":
                await suspender(s, empresa.id, operador.email, motivo=corpo.motivo)
            elif corpo.para == "encerrado":
                await encerrar(s, empresa.id, operador.email, motivo=corpo.motivo)
            elif atual == Estado.SUSPENSO.value:
                await retomar(s, empresa.id, operador.email)
            else:
                prontidao = await ativar(s, empresa.id, canal, operador.email)
                if not prontidao.aprovada:
                    reprovada = [
                        {"id": i.nome, "ok": i.ok, "rotulo": i.nome, "detalhe": i.detalhe}
                        for i in prontidao.itens
                    ]
        except TransicaoInvalida as exc:
            raise ErroAdmin(
                409,
                "transicao_invalida",
                str(exc),
                extras={"estado_atual": atual, "permitidos": _permitidos(atual)},
            ) from exc
        if reprovada is None:
            empresa.versao += 1
    if reprovada is not None:  # a verificação foi gravada; o estado não mudou
        raise ErroAdmin(
            409,
            "prontidao_reprovada",
            "A prontidão não foi aprovada: a empresa não foi ativada.",
            extras={"itens": reprovada},
        )
    return await _resposta(slug)


@router.post("/empresas/{slug}/prontidao")
async def avaliar_prontidao_da_empresa(
    slug: Slug, operador: Escritor, canal: Canal
) -> dict[str, Any]:
    async with admin_session() as s:
        empresa = await _travar(s, slug, None)
        resultado = await avaliar_prontidao(s, empresa.id, canal, operador.email)
    return {
        "aprovada": resultado.aprovada,
        "itens": [{"id": i.nome, "ok": i.ok, "detalhe": i.detalhe} for i in resultado.itens],
    }


# --- Documentos ---------------------------------------------------------------------------------


def _extensao(nome: str) -> str:
    return "." + nome.rsplit(".", 1)[-1].lower() if "." in nome else ""


@router.post("/empresas/{slug}/documentos", status_code=202)
async def enviar_documentos(
    slug: Slug,
    corpo: EnviarDocumentos,
    operador: Escritor,
    redis: RedisDep,
    fila: Annotated[Any, Depends(get_queue)],
) -> dict[str, Any]:
    nomes = [a.nome for a in corpo.arquivos]
    if len(set(nomes)) != len(nomes):
        raise ErroAdmin(
            400,
            "validacao",
            "Corrija os campos indicados.",
            campos={"arquivos": "Há arquivos com o mesmo nome na remessa."},
        )
    conteudos: list[bytes] = []
    for arquivo in corpo.arquivos:
        if _extensao(arquivo.nome) not in EXTENSOES_SUPORTADAS:
            raise ErroAdmin(
                415,
                "formato_nao_suportado",
                f"Formato não suportado: use {', '.join(sorted(EXTENSOES_SUPORTADAS))}.",
                campos={"arquivos": f"'{arquivo.nome}': formato não suportado."},
            )
        try:
            bruto = base64.b64decode(arquivo.conteudo_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ErroAdmin(
                400,
                "validacao",
                "Corrija os campos indicados.",
                campos={"arquivos": f"'{arquivo.nome}': conteúdo inválido."},
            ) from exc
        if len(bruto) > TAMANHO_MAXIMO_ARQUIVO:
            raise ErroAdmin(
                413,
                "arquivo_grande",
                "Arquivo acima do limite de 2 MB.",
                campos={"arquivos": f"'{arquivo.nome}': acima de 2 MB."},
            )
        conteudos.append(bruto)
    async with admin_session() as s:
        empresa = await _travar(s, slug, None)
        if empresa.status == Estado.ENCERRADO.value:
            raise ErroAdmin(409, "empresa_encerrada", "Empresa encerrada não pode ser editada.")
        tenant_id = empresa.id
    remessa = uuid.uuid4().hex
    base = PREFIXO_REMESSA + remessa
    await redis.set(
        base + ":meta",
        json.dumps(
            {"slug": slug, "tenant_id": str(tenant_id), "nomes": nomes, "operador": operador.email}
        ),
        ex=VALIDADE_REMESSA_S,
    )
    for i, bruto in enumerate(conteudos):
        await redis.set(f"{base}:arq:{i}", bruto, ex=VALIDADE_REMESSA_S)
    await fila.enqueue_job("ingerir_remessa", remessa)
    return {"remessa": remessa}


@router.get("/empresas/{slug}/documentos/remessas/{remessa}")
async def resultado_da_remessa(
    slug: Slug,
    remessa: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")],
    operador: OperadorAtual,
    redis: RedisDep,
) -> dict[str, Any]:
    bruto = await redis.get(f"{PREFIXO_REMESSA}{remessa}:meta")
    if bruto is None or json.loads(bruto)["slug"] != slug:
        raise ErroAdmin(404, "remessa_nao_encontrada", "Remessa não encontrada ou expirada.")
    meta = json.loads(bruto)
    res = await redis.get(f"{PREFIXO_REMESSA}{remessa}:res")
    if res is None:
        return {
            "estado": "processando",
            "arquivos": [{"nome": n, "status": "processando"} for n in meta["nomes"]],
            "base": None,
        }
    resultado = json.loads(res)
    ficha = await ficha_do_painel.ficha(slug)
    return {"estado": "concluida", "arquivos": resultado["arquivos"], "base": ficha["base"]}


# --- Apagar dados (US4, P3) ---------------------------------------------------------------------


@router.get("/empresas/{slug}/apagar-dados/resumo")
async def resumo_do_apagamento(slug: Slug, operador: Escritor) -> dict[str, Any]:
    async with admin_session() as s:
        empresa = await _travar(s, slug, None)
        contagens: dict[str, int] = {}
        for nome, modelo in ORDEM_DE_EXCLUSAO:
            total = (
                await s.execute(
                    select(func.count()).select_from(modelo).where(modelo.tenant_id == empresa.id)
                )
            ).scalar_one()
            contagens[nome] = int(total)
    return {
        "estado": empresa.status,
        "pode_apagar": empresa.status == Estado.ENCERRADO.value
        and empresa.dados_apagados_em is None,
        "dados_apagados_em": empresa.dados_apagados_em.isoformat()
        if empresa.dados_apagados_em
        else None,
        "contagens": contagens,
    }


@router.post("/empresas/{slug}/apagar-dados")
async def apagar_dados_da_empresa(
    slug: Slug, corpo: ConfirmarApagamento, operador: Escritor, redis: RedisDep
) -> dict[str, Any]:
    async with admin_session() as s:
        empresa = await _travar(s, slug, None)
        tenant_id = empresa.id
    try:
        resultado = await apagar_dados(
            admin_session,
            tenant_id,
            corpo.confirmacao,
            operador.email,
            redis=redis,
            drenagem_segundos=settings.purge_drenagem_segundos,
        )
    except ExclusaoRecusada as exc:
        raise ErroAdmin(409, "exclusao_recusada", str(exc)) from exc
    return {"apagado": resultado.contagens, "instancia_liberada": resultado.instance_name}
