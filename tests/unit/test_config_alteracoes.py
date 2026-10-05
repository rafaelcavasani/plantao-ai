"""Alteração de configuração por empresa: leitura de `campo=valor` e validação conjunta (T071, FR-009, FR-010)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.tenancy.config import (
    CAMPOS_CONFIG,
    ConfigEmpresa,
    ConfigInvalida,
    aplicar_alteracoes,
    interpretar_atribuicoes,
)
from db.models import AuditLog

TENANT = uuid.uuid4()


class SessaoFalsa:
    """Só o que `aplicar_alteracoes` usa: `get`, `add` e `flush`."""

    def __init__(self, linha: Any) -> None:
        self.linha = linha
        self.adicionados: list[AuditLog] = []

    async def get(self, _modelo: Any, _chave: Any) -> Any:
        return self.linha

    def add(self, objeto: AuditLog) -> None:
        self.adicionados.append(objeto)

    async def flush(self) -> None:
        return None


def _sessao(**alterados: Any) -> SessaoFalsa:
    base = ConfigEmpresa().como_dict()
    return SessaoFalsa(SimpleNamespace(**{**base, **alterados}))


async def _aplicar(sessao: SessaoFalsa, alteracoes: dict[str, Any]) -> list[str]:
    return await aplicar_alteracoes(cast(AsyncSession, sessao), TENANT, alteracoes, "rafael")


# --- campo=valor ------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("par", "esperado"),
    [
        ("min_similarity=0.8", 0.8),
        ("handoff_ttl_minutos=30", 30),
        ('palavras_gatilho=["a","b"]', ["a", "b"]),
        ('horario_funcionamento={"seg_sex":"08:00-18:00"}', {"seg_sex": "08:00-18:00"}),
        ('tom_de_voz="formal"', "formal"),
        ("tom_de_voz=formal", "formal"),
        ("tom_de_voz=cordial e direto", "cordial e direto"),
        ("tom_de_voz=a=b", "a=b"),
        ("topicos_proibidos=[]", []),
    ],
)
def test_valor_e_json_e_texto_sem_aspas_vira_string(par: str, esperado: Any) -> None:
    campo = par.split("=", 1)[0]
    assert interpretar_atribuicoes([par]) == {campo: esperado}


def test_varios_pares_viram_um_dict() -> None:
    assert interpretar_atribuicoes(["min_similarity=0.5", "tom_de_voz=formal"]) == {
        "min_similarity": 0.5,
        "tom_de_voz": "formal",
    }


@pytest.mark.parametrize("par", ["sem_igual", "=0.5", "", "  =x"])
def test_par_malformado_e_recusado(par: str) -> None:
    with pytest.raises(ConfigInvalida) as exc:
        interpretar_atribuicoes([par])
    assert "use campo=valor" in exc.value.erros[0]


def test_campo_repetido_e_recusado_e_todos_os_problemas_sao_listados() -> None:
    with pytest.raises(ConfigInvalida) as exc:
        interpretar_atribuicoes(["min_similarity=0.5", "min_similarity=0.6", "xyz"])
    assert len(exc.value.erros) == 2
    assert any("min_similarity: informado mais de uma vez" in e for e in exc.value.erros)


# --- validação ---------------------------------------------------------------------------------------
async def test_campo_desconhecido_e_erro_e_nada_e_gravado() -> None:
    sessao = _sessao()
    with pytest.raises(ConfigInvalida) as exc:
        await _aplicar(sessao, {"campo_inventado": 1, "min_similarity": 0.9})
    assert exc.value.erros == ["campo_inventado: campo desconhecido"]
    assert sessao.linha.min_similarity == ConfigEmpresa().min_similarity
    assert sessao.adicionados == []


async def test_varios_campos_sao_validados_juntos_e_cada_invalido_e_listado() -> None:
    sessao = _sessao()
    with pytest.raises(ConfigInvalida) as exc:
        await _aplicar(
            sessao,
            {
                "min_similarity": 1.5,  # inválido
                "handoff_ttl_minutos": 30,  # válido, mas sofre a recusa do conjunto
                "horario_funcionamento": {"seg": "8h-18h"},  # inválido
            },
        )
    campos = {e.split(":", 1)[0] for e in exc.value.erros}
    assert {"min_similarity", "horario_funcionamento"} <= campos
    assert sessao.linha.handoff_ttl_minutos == ConfigEmpresa().handoff_ttl_minutos
    assert sessao.adicionados == []


async def test_mensagem_de_erro_nao_ecoa_o_valor_recebido() -> None:
    with pytest.raises(ConfigInvalida) as exc:
        await _aplicar(_sessao(), {"tom_de_voz": ["segredo-no-valor"]})
    assert "segredo-no-valor" not in str(exc.value)


async def test_valor_valido_grava_e_audita_so_o_que_mudou() -> None:
    sessao = _sessao()
    atual = ConfigEmpresa()

    alterados = await _aplicar(
        sessao,
        {"min_similarity": 0.9, "tom_de_voz": atual.tom_de_voz},  # o segundo não muda
    )

    assert alterados == ["min_similarity"]
    assert sessao.linha.min_similarity == 0.9
    [auditoria] = sessao.adicionados
    assert (auditoria.entidade, auditoria.campo, auditoria.operador) == (
        "config",
        "min_similarity",
        "rafael",
    )
    assert (auditoria.valor_anterior, auditoria.valor_novo) == (atual.min_similarity, 0.9)


async def test_sem_mudanca_nao_gera_auditoria() -> None:
    sessao = _sessao()
    assert await _aplicar(sessao, {"min_similarity": ConfigEmpresa().min_similarity}) == []
    assert sessao.adicionados == []


async def test_uma_linha_de_auditoria_por_campo() -> None:
    sessao = _sessao()
    alterados = await _aplicar(
        sessao, {"min_similarity": 0.9, "handoff_ttl_minutos": 45, "topicos_proibidos": ["x"]}
    )
    assert alterados == ["min_similarity", "handoff_ttl_minutos", "topicos_proibidos"]
    assert [a.campo for a in sessao.adicionados] == alterados
    assert set(alterados) <= set(CAMPOS_CONFIG)


async def test_empresa_sem_configuracao_e_erro() -> None:
    with pytest.raises(LookupError):
        await _aplicar(SessaoFalsa(None), {"min_similarity": 0.9})
