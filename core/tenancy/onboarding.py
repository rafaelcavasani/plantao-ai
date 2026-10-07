"""Onboarding repetível de uma empresa a partir de um arquivo (FR-012, FR-013; research R-09).

O arquivo não tem segredos: as credenciais entram por **nome** de variável de ambiente. Tudo é validado antes
de qualquer escrita. Cada passo é um upsert na própria transação, então repetir o comando continua de onde
parou e não duplica nada. Empresa `ativo` nunca é rebaixada.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    ValidationInfo,
    field_validator,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.llm.ports import LLMClient
from core.rag.ingest import STATUS_DE_FALHA, ResultadoIngestao, ingerir_documento
from core.tenancy.auditoria import registrar_mudanca
from core.tenancy.ciclo_vida import Estado
from core.tenancy.conexoes import (
    TAMANHO_MINIMO_SEGREDO,
    ConexaoEmUso,
    cadastrar_conexao,
)
from core.tenancy.config import ConfigEmpresa, aplicar_alteracoes, erros_de_validacao
from db.config_padrao import nova_config_padrao
from db.models import ChannelConnection, Tenant, TenantConfig

SessaoAdmin = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class ArquivoInvalido(ValueError):
    """Arquivo ilegível ou com valores inválidos. `erros` traz um item `campo: motivo` por campo."""

    def __init__(self, erros: list[str]) -> None:
        super().__init__("; ".join(erros))
        self.erros = erros


class OnboardingRecusado(Exception):
    """A empresa ou a instância não podem ser tratadas (instância de outra empresa, empresa encerrada)."""


def _variavel(nome: str) -> str:
    valor = os.environ.get(nome, "")
    if not valor:
        raise ValueError(f"variavel de ambiente '{nome}' ausente ou vazia")
    return valor


class CanalArquivo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo: Literal["whatsapp"]
    provedor: Literal["evolution"] = "evolution"
    instance_name: Annotated[str, Field(min_length=1, max_length=100)]
    api_key_env: str
    webhook_secret_env: str

    @field_validator("api_key_env")
    @classmethod
    def _chave_existe(cls, nome: str) -> str:
        _variavel(nome)
        return nome

    @field_validator("webhook_secret_env")
    @classmethod
    def _segredo_forte(cls, nome: str) -> str:
        if len(_variavel(nome)) < TAMANHO_MINIMO_SEGREDO:
            raise ValueError(
                f"a variavel '{nome}' precisa ter pelo menos {TAMANHO_MINIMO_SEGREDO} caracteres"
            )
        return nome


class DocumentosArquivo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pasta: str

    @field_validator("pasta")
    @classmethod
    def _pasta_existe(cls, pasta: str, info: ValidationInfo) -> str:
        base = (info.context or {}).get("base")
        if base is not None and not (Path(base) / pasta).is_dir():
            raise ValueError("pasta nao encontrada")
        return pasta


class TesteArquivo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pergunta: Annotated[str, Field(min_length=1)]
    esperado: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)


class ArquivoEmpresa(BaseModel):
    """Esquema do arquivo de onboarding. Campo desconhecido é erro (pega erro de digitação)."""

    model_config = ConfigDict(extra="forbid")

    slug: Annotated[str, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", min_length=3, max_length=63)]
    nome_empresa: Annotated[str, Field(min_length=2, max_length=255)]
    nicho: Annotated[str, Field(min_length=1, max_length=100)]
    plano: Annotated[str, Field(min_length=1, max_length=50)] = "recepcionista"
    configuracao: ConfigEmpresa = Field(default_factory=ConfigEmpresa)
    canal: CanalArquivo
    documentos: DocumentosArquivo | None = None
    teste_prontidao: TesteArquivo | None = None

    _base: Path = PrivateAttr(default=Path("."))

    @property
    def base(self) -> Path:
        """Pasta do arquivo YAML; caminhos relativos do arquivo partem dela."""
        return self._base

    def campos_de_config_informados(self) -> dict[str, Any]:
        """Só os campos que o arquivo trouxe; o resto não é tocado em empresa existente."""
        valores = self.configuracao.como_dict()
        return {c: valores[c] for c in self.configuracao.model_fields_set}


def carregar_arquivo(caminho: Path) -> ArquivoEmpresa:
    """Lê e valida o arquivo. Levanta `ArquivoInvalido` com um erro por campo."""
    try:
        dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ArquivoInvalido([f"arquivo: nao foi possivel ler ({type(exc).__name__})"]) from exc
    except yaml.YAMLError as exc:
        raise ArquivoInvalido(["arquivo: YAML invalido"]) from exc
    if not isinstance(dados, dict):
        raise ArquivoInvalido(["arquivo: esperado um mapa de campos"])
    base = caminho.resolve().parent
    try:
        arquivo = ArquivoEmpresa.model_validate(dados, context={"base": base})
    except ValidationError as exc:
        raise ArquivoInvalido(erros_de_validacao(exc)) from exc
    arquivo._base = base
    return arquivo


def carregar_teste(caminho: Path) -> tuple[str, TesteArquivo]:
    """`(slug, teste_prontidao)` do arquivo, sem exigir as variáveis de credencial (comando `test`)."""
    try:
        dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ArquivoInvalido(["arquivo: nao foi possivel ler"]) from exc
    if not isinstance(dados, dict) or not isinstance(dados.get("slug"), str):
        raise ArquivoInvalido(["slug: obrigatorio"])
    if not isinstance(dados.get("teste_prontidao"), dict):
        raise ArquivoInvalido(["teste_prontidao: obrigatorio para o comando test"])
    try:
        return dados["slug"], TesteArquivo.model_validate(dados["teste_prontidao"])
    except ValidationError as exc:
        raise ArquivoInvalido(erros_de_validacao(exc, "teste_prontidao.")) from exc


@dataclass(frozen=True)
class PassoCriacao:
    nome: str
    ok: bool
    segundos: float
    detalhe: str = ""


@dataclass
class ResultadoCriacao:
    tenant_id: uuid.UUID
    slug: str
    novo: bool
    estado: str = Estado.EM_CONFIGURACAO.value
    passos: list[PassoCriacao] = field(default_factory=list)
    documentos: list[ResultadoIngestao] = field(default_factory=list)

    @property
    def falhou(self) -> bool:
        return any(not p.ok for p in self.passos)


async def garantir_empresa(
    s: AsyncSession,
    *,
    slug: str,
    nome_empresa: str,
    nicho: str,
    plano: str,
    instance_name: str | None,
    operador: str,
) -> tuple[uuid.UUID, bool, str]:
    """Cria a empresa em configuração ou atualiza nome, nicho e plano da existente (auditado).

    Compartilhado pelo CLI (`criar_ou_continuar`) e pelo painel, para os dois produzirem o mesmo resultado.
    `s` é administrativa e a transação é do chamador (sem commit). Devolve `(tenant_id, nova, estado)`.
    `OnboardingRecusado` se a empresa está encerrada; `ConexaoEmUso` se a instância é de outra empresa.
    """
    existente = (await s.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    dono = None
    if instance_name is not None:
        dono = (
            await s.execute(
                select(ChannelConnection.tenant_id).where(
                    ChannelConnection.instance_name == instance_name
                )
            )
        ).scalar_one_or_none()
    if existente is not None and existente.status == Estado.ENCERRADO.value:
        raise OnboardingRecusado(f"A empresa '{slug}' esta encerrada.")
    if dono is not None and (existente is None or dono != existente.id):
        raise ConexaoEmUso(f"A instancia '{instance_name}' ja esta em uso por outra empresa.")
    if existente is None:
        empresa = Tenant(
            nome_empresa=nome_empresa,
            slug=slug,
            nicho=nicho,
            plano=plano,
            status=Estado.EM_CONFIGURACAO.value,
        )
        s.add(empresa)
        await s.flush()
        s.add(TenantConfig(tenant_id=empresa.id, **nova_config_padrao()))
        await s.flush()
        return empresa.id, True, empresa.status
    for campo, novo in (("nome_empresa", nome_empresa), ("nicho", nicho), ("plano", plano)):
        anterior = getattr(existente, campo)
        if anterior != novo:
            await registrar_mudanca(s, existente.id, "config", campo, anterior, novo, operador)
            setattr(existente, campo, novo)
    return existente.id, False, existente.status


async def _empresa(
    sessao_admin: SessaoAdmin, arquivo: ArquivoEmpresa, operador: str
) -> tuple[uuid.UUID, bool, str]:
    async with sessao_admin() as s:
        return await garantir_empresa(
            s,
            slug=arquivo.slug,
            nome_empresa=arquivo.nome_empresa,
            nicho=arquivo.nicho,
            plano=arquivo.plano,
            instance_name=arquivo.canal.instance_name,
            operador=operador,
        )


async def criar_ou_continuar(
    arquivo: ArquivoEmpresa,
    *,
    operador: str,
    llm: LLMClient | None,
    sessao_admin: SessaoAdmin,
) -> ResultadoCriacao:
    """Cria a empresa ou continua de onde parou. Levanta `ConexaoEmUso` ou `OnboardingRecusado`
    antes de gravar o que for novo. Falha de documento não aborta: fica no resultado.
    `llm` só é usado se o arquivo tiver `documentos`."""
    if arquivo.documentos is not None and llm is None:
        raise ValueError("llm obrigatorio quando o arquivo tem documentos")
    passos: list[PassoCriacao] = []
    inicio = time.perf_counter()
    tenant_id, novo, estado = await _empresa(sessao_admin, arquivo, operador)
    passos.append(
        PassoCriacao("empresa", True, time.perf_counter() - inicio, "novo" if novo else "existente")
    )
    resultado = ResultadoCriacao(tenant_id, arquivo.slug, novo, estado, passos)

    inicio = time.perf_counter()
    async with sessao_admin() as s:
        alterados = await aplicar_alteracoes(
            s, tenant_id, arquivo.campos_de_config_informados(), operador
        )
    passos.append(
        PassoCriacao(
            "configuracao",
            True,
            time.perf_counter() - inicio,
            f"campos alterados: {len(alterados)}",
        )
    )

    inicio = time.perf_counter()
    async with sessao_admin() as s:
        cadastro = await cadastrar_conexao(
            s,
            tenant_id,
            instance_name=arquivo.canal.instance_name,
            webhook_secret=_variavel(arquivo.canal.webhook_secret_env),
            api_key=_variavel(arquivo.canal.api_key_env),
            operador=operador,
            canal=arquivo.canal.tipo,
            provedor=arquivo.canal.provedor,
        )
    segundos = time.perf_counter() - inicio
    passos.append(
        PassoCriacao("conexao", True, segundos, f"instancia: {arquivo.canal.instance_name}")
    )
    passos.append(
        PassoCriacao(
            "credenciais", True, 0.0, "atualizadas" if cadastro.alterada else "inalteradas"
        )
    )

    inicio = time.perf_counter()
    if arquivo.documentos is not None:
        pasta = arquivo.base / arquivo.documentos.pasta
        arquivos = sorted(
            p for p in await asyncio.to_thread(lambda: list(pasta.iterdir())) if p.is_file()
        )
        for caminho in arquivos:
            assert llm is not None
            resultado.documentos.append(
                await ingerir_documento(
                    llm,
                    tenant_id=tenant_id,
                    nome_origem=caminho.name,
                    conteudo=await asyncio.to_thread(caminho.read_bytes),
                )
            )
    docs = resultado.documentos
    falhas = sum(d.status in STATUS_DE_FALHA for d in docs)
    custo = sum((d.custo_usd for d in docs), Decimal(0))
    passos.append(
        PassoCriacao(
            "documentos",
            falhas == 0,
            time.perf_counter() - inicio,
            f"{sum(d.status == 'ok' for d in docs)} ok, "
            f"{sum(d.status == 'inalterado' for d in docs)} inalterados, {falhas} falhas   "
            f"custo_usd={custo:f}",
        )
    )
    passos.append(PassoCriacao("resumo", True, 0.0))
    return resultado
