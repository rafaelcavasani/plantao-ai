"""Multi-tenancy: configuração, ciclo de vida, auditoria, conexões, onboarding e prontidão por empresa."""

from core.tenancy.auditoria import MARCA_CREDENCIAL, registrar_mudanca
from core.tenancy.ciclo_vida import (
    TRANSICOES,
    Estado,
    TransicaoInvalida,
    mudar_estado,
    retomar,
    suspender,
    validar_transicao,
)
from core.tenancy.conexoes import (
    ConexaoCadastrada,
    ConexaoEmUso,
    SegredoInvalido,
    cadastrar_conexao,
    hash_segredo,
)
from core.tenancy.config import (
    CAMPOS_CONFIG,
    ConfigEmpresa,
    ConfigInvalida,
    aplicar_alteracoes,
)
from core.tenancy.empresas import EmpresaNaoEncontrada, listar, obter_por_slug
from core.tenancy.exclusao import (
    ExclusaoRecusada,
    ResultadoExclusao,
    apagar_dados,
    encerrar,
)
from core.tenancy.resolucao import (
    ConexaoAusente,
    ConexaoRoteada,
    autenticar_entrega,
    carregar_conexao_canal,
    resolver_conexao,
)

__all__ = [
    "CAMPOS_CONFIG",
    "MARCA_CREDENCIAL",
    "TRANSICOES",
    "ConexaoAusente",
    "ConexaoCadastrada",
    "ConexaoEmUso",
    "ConexaoRoteada",
    "ConfigEmpresa",
    "ConfigInvalida",
    "EmpresaNaoEncontrada",
    "Estado",
    "ExclusaoRecusada",
    "ResultadoExclusao",
    "SegredoInvalido",
    "TransicaoInvalida",
    "apagar_dados",
    "aplicar_alteracoes",
    "autenticar_entrega",
    "cadastrar_conexao",
    "carregar_conexao_canal",
    "encerrar",
    "hash_segredo",
    "listar",
    "mudar_estado",
    "obter_por_slug",
    "registrar_mudanca",
    "resolver_conexao",
    "retomar",
    "suspender",
    "validar_transicao",
]
