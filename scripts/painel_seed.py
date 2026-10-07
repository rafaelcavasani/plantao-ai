"""Dados de demonstração para o painel de operação (spec 004, T081).

Cria empresas fictícias (`<prefixo>-01`, `<prefixo>-02`...) com histórico de conversas, mensagens, handoffs e
chamadas de LLM, e roda a agregação do painel. Usa só texto de demonstração (nada de dado real) e é repetível:
empresa que já existe é pulada. Uso:

    python -m scripts.painel_seed --empresas 5 --dias 30 --conversas-por-dia 20
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.painel.agregacao import recalcular_todas
from db.admin import admin_session, fechar_admin_engine
from db.config_padrao import nova_config_padrao
from db.models import ChannelConnection, ChannelCredential, Tenant, TenantConfig
from scripts.verificar_migracao import exigir_migracao

NICHOS = [
    "Clínica odontológica",
    "Academia",
    "Imobiliária",
    "Pet shop",
    "Barbearia",
    "Escola de idiomas",
]
PLANOS = ["recepcionista", "recepcionista_agendador", "pacote_completo"]

_SQL_CONVERSAS = text(
    """
    INSERT INTO conversations (id, tenant_id, canal, contato_hash, contato_enc, status, agente_atual,
                               iniciado_em, ultima_atividade_em, iniciada_por)
    SELECT gen_random_uuid(), :t, 'whatsapp', md5(random()::text), 'contato-de-demonstracao',
           CASE WHEN random() < :p_handoff THEN 'handoff' WHEN random() < 0.7 THEN 'resolvida' ELSE 'aberta' END,
           CASE WHEN random() < :p_handoff THEN 'humano' ELSE 'support' END,
           ts, ts + interval '3 minutes', 'contato'
    FROM generate_series(:inicio, :fim, make_interval(secs => :passo)) AS ts
    """
)
_SQL_MENSAGENS = text(
    """
    WITH entradas AS (
        INSERT INTO messages (id, tenant_id, conversation_id, remetente, conteudo, tipo, external_id, intencao,
                              intencao_confianca, timestamp)
        SELECT gen_random_uuid(), c.tenant_id, c.id, 'lead', 'mensagem de demonstração', 'texto',
               md5(c.id::text || 'lead'),
               (ARRAY['duvida', 'agendamento', 'preco', 'suporte'])[1 + floor(random() * 4)::int],
               0.9, c.iniciado_em
        FROM conversations c WHERE c.tenant_id = :t AND c.contato_enc = 'contato-de-demonstracao'
          AND c.iniciado_em >= :inicio AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id)
        RETURNING id, conversation_id, timestamp
    )
    INSERT INTO messages (id, tenant_id, conversation_id, remetente, conteudo, tipo, status_envio, responde_a,
                          timestamp)
    SELECT gen_random_uuid(), :t, e.conversation_id, 'agente', 'resposta de demonstração', 'texto',
           CASE WHEN random() < 0.01 THEN 'falha' ELSE 'enviada' END, e.id,
           e.timestamp + make_interval(secs => 1 + random() * 12)
    FROM entradas e
    """
)
_SQL_HANDOFFS = text(
    """
    INSERT INTO handoff_log (id, tenant_id, conversation_id, motivo, confianca_no_momento, resolvido_por_humano,
                             criado_em)
    SELECT gen_random_uuid(), c.tenant_id, c.id,
           (ARRAY['confianca_abaixo_do_minimo', 'palavra_gatilho:procon', 'nao_texto'])[1 + floor(random() * 3)::int],
           random() * 0.6, random() < 0.8, c.iniciado_em + interval '1 minute'
    FROM conversations c
    WHERE c.tenant_id = :t AND c.status = 'handoff' AND c.contato_enc = 'contato-de-demonstracao'
      AND c.iniciado_em >= :inicio
      AND NOT EXISTS (SELECT 1 FROM handoff_log h WHERE h.conversation_id = c.id)
    """
)
_SQL_LLM = text(
    """
    INSERT INTO llm_calls (id, tenant_id, conversation_id, finalidade, modelo, tokens_entrada, tokens_saida,
                           custo_usd, latencia_ms, sucesso, criado_em)
    SELECT gen_random_uuid(), c.tenant_id, c.id, f.finalidade, f.modelo, f.tin, f.tout, f.custo,
           400 + floor(random() * 900)::int, true, c.iniciado_em + interval '1 second'
    FROM conversations c
    CROSS JOIN (VALUES ('roteador', 'anthropic/claude-3-haiku', 180, 12, 0.00006),
                       ('suporte', 'anthropic/claude-3.5-sonnet', 900, 160, 0.0051)) AS f(finalidade, modelo, tin, tout, custo)
    WHERE c.tenant_id = :t AND c.contato_enc = 'contato-de-demonstracao' AND c.iniciado_em >= :inicio
      AND NOT EXISTS (SELECT 1 FROM llm_calls l WHERE l.conversation_id = c.id)
    """
)


async def semear_historico(
    s: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    dias: int,
    conversas_por_dia: int,
    taxa_handoff: float = 0.12,
    agora: datetime | None = None,
) -> int:
    """Insere o histórico de uma empresa por SQL em lote. Devolve o número de conversas pedidas."""
    fim = agora or datetime.now(UTC)
    inicio = fim - timedelta(days=dias)
    total = max(1, dias * conversas_por_dia)
    await s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
    parametros = {"t": tenant_id, "inicio": inicio, "fim": fim}
    await s.execute(
        _SQL_CONVERSAS, {**parametros, "passo": (dias * 86400) / total, "p_handoff": taxa_handoff}
    )
    await s.execute(_SQL_MENSAGENS, {"t": tenant_id, "inicio": inicio})
    await s.execute(_SQL_HANDOFFS, {"t": tenant_id, "inicio": inicio})
    await s.execute(_SQL_LLM, {"t": tenant_id, "inicio": inicio})
    return total


async def criar_empresa_demo(
    s: AsyncSession, indice: int, prefixo: str, total: int
) -> tuple[uuid.UUID, bool]:
    slug = f"{prefixo}-{indice:02d}"
    existente = (await s.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if existente is not None:
        return existente.id, False
    ultima = indice == total and total > 2
    estado = (
        "em_configuracao"
        if ultima
        else ("suspenso" if indice == total - 1 and total > 3 else "ativo")
    )
    empresa = Tenant(
        nome_empresa=f"Empresa Demo {indice:02d}",
        slug=slug,
        nicho=NICHOS[indice % len(NICHOS)],
        plano=PLANOS[indice % len(PLANOS)],
        status=estado,
        ativado_em=None if estado == "em_configuracao" else datetime.now(UTC) - timedelta(days=60),
    )
    s.add(empresa)
    await s.flush()
    config = nova_config_padrao()
    config["horario_funcionamento"] = {"seg_sex": "08:00-18:00"}
    s.add(TenantConfig(tenant_id=empresa.id, **config))
    if not ultima:
        conexao = ChannelConnection(
            tenant_id=empresa.id,
            canal="whatsapp",
            provedor="evolution",
            instance_name=f"{slug}-wa",
            verificada_em=datetime.now(UTC) if indice % 4 else None,
        )
        s.add(conexao)
        await s.flush()
        s.add(
            ChannelCredential(
                connection_id=conexao.id,
                tenant_id=empresa.id,
                webhook_secret_hash="demo",
                api_key_enc="demo",
            )
        )
    await s.flush()
    return empresa.id, True


async def principal(empresas: int, dias: int, conversas_por_dia: int, prefixo: str) -> None:
    await exigir_migracao()
    novas = 0
    for i in range(1, empresas + 1):
        async with admin_session() as s:
            tenant_id, nova = await criar_empresa_demo(s, i, prefixo, empresas)
            if nova:
                await s.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
                )
                estado = (
                    await s.execute(select(Tenant.status).where(Tenant.id == tenant_id))
                ).scalar_one()
                if estado != "em_configuracao":
                    await semear_historico(
                        s, tenant_id, dias=dias, conversas_por_dia=conversas_por_dia
                    )
                novas += 1
    resultado = await recalcular_todas(janela_horas=dias * 24 + 24)
    print(
        f"{novas} empresa(s) nova(s); agregação: {resultado.empresas} empresa(s), {resultado.horas} hora(s)"
    )
    if resultado.falhas:
        print("falhas:", "; ".join(resultado.falhas))
    await fechar_admin_engine()


def main() -> None:
    ap = argparse.ArgumentParser(description="Semeia dados de demonstração para o painel.")
    ap.add_argument("--empresas", type=int, default=5)
    ap.add_argument("--dias", type=int, default=30)
    ap.add_argument("--conversas-por-dia", type=int, default=20)
    ap.add_argument("--prefixo", default="demo")
    a = ap.parse_args()
    asyncio.run(principal(a.empresas, a.dias, a.conversas_por_dia, a.prefixo))


if __name__ == "__main__":
    main()
