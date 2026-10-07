"""Conversas por metadados, sem texto nem contato (spec 004, T075 e T076; US5, FR-005)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from db.models import Conversation, HandoffLog, Message
from db.painel import painel_session
from tests.fakes.painel import AdminApi, chaves_proibidas

pytestmark = [pytest.mark.integration, pytest.mark.contract]

SEGREDO_TEXTO = "TEXTO-QUE-NAO-PODE-VAZAR"
SEGREDO_TEL = "+55 11 98888-7777"
T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


async def semear(db: AsyncEngine, t: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSession(db, expire_on_commit=False) as s:
        c1 = Conversation(
            id=uuid.uuid4(),
            tenant_id=t,
            canal="whatsapp",
            contato_hash="h",
            contato_enc=SEGREDO_TEL,
            status="handoff",
            agente_atual="humano",
            iniciado_em=T0,
            ultima_atividade_em=T0 + timedelta(minutes=5),
        )
        c2 = Conversation(
            id=uuid.uuid4(),
            tenant_id=t,
            canal="whatsapp",
            contato_hash="h2",
            contato_enc="e2",
            status="aberta",
            iniciado_em=T0,
            ultima_atividade_em=T0 + timedelta(minutes=1),
        )
        s.add_all([c1, c2])
        await s.flush()
        m1 = Message(
            id=uuid.uuid4(),
            tenant_id=t,
            conversation_id=c1.id,
            remetente="lead",
            conteudo=SEGREDO_TEXTO,
            external_id="ext-1",
            intencao="suporte",
            intencao_confianca=0.9,
            timestamp=T0,
        )
        s.add(m1)
        await s.flush()
        s.add_all(
            [
                Message(
                    id=uuid.uuid4(),
                    tenant_id=t,
                    conversation_id=c1.id,
                    remetente="agente",
                    conteudo=SEGREDO_TEXTO,
                    responde_a=m1.id,
                    status_envio="enviada",
                    timestamp=T0 + timedelta(seconds=2),
                ),
                Message(
                    id=uuid.uuid4(),
                    tenant_id=t,
                    conversation_id=c1.id,
                    remetente="lead",
                    conteudo=SEGREDO_TEXTO,
                    tipo="nao_texto",
                    external_id="ext-2",
                    timestamp=T0 + timedelta(minutes=1),
                ),
                HandoffLog(
                    tenant_id=t,
                    conversation_id=c1.id,
                    motivo="nao_texto",
                    confianca_no_momento=0.4,
                    criado_em=T0 + timedelta(minutes=1),
                ),
            ]
        )
        await s.commit()
    return c1.id, c2.id


async def slug_de(db: AsyncEngine, t: uuid.UUID) -> str:
    async with db.connect() as conn:
        return str(
            (
                await conn.execute(text("SELECT slug FROM tenants WHERE id = :t"), {"t": t})
            ).scalar_one()
        )


async def test_lista_so_tem_metadados(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    c1, _ = await semear(db, tenant_a)
    await semear(db, tenant_b)
    slug = await slug_de(db, tenant_a)
    r = await admin_api.get(f"/admin/empresas/{slug}/conversas")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["total"] == 2  # só as da empresa A
    assert set(corpo["itens"][0]) == {
        "id_curto",
        "id",
        "canal",
        "status",
        "agente_atual",
        "iniciada_em",
        "ultima_atividade_em",
        "total_mensagens",
    }
    primeira = corpo["itens"][0]
    assert (
        primeira["id"] == str(c1)
        and primeira["id_curto"] == str(c1)[:8]
        and primeira["total_mensagens"] == 3
    )
    assert chaves_proibidas(corpo) == []
    assert SEGREDO_TEXTO not in r.text and SEGREDO_TEL not in r.text and "98888" not in r.text


async def test_detalhe_traz_handoff_e_linha_do_tempo_sem_texto(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    c1, _ = await semear(db, tenant_a)
    slug = await slug_de(db, tenant_a)
    r = await admin_api.get(f"/admin/empresas/{slug}/conversas/{c1}")
    assert r.status_code == 200
    d = r.json()
    assert d["handoff"] == {
        "motivo": "nao_texto",
        "confianca": 0.4,
        "em": (T0 + timedelta(minutes=1)).isoformat(),
    }
    assert [m["remetente"] for m in d["linha_do_tempo"]] == ["lead", "agente", "lead"]
    assert (
        d["linha_do_tempo"][0]["intencao"] == "suporte"
        and d["linha_do_tempo"][1]["status_envio"] == "enviada"
    )
    assert d["linha_do_tempo"][2]["tipo"] == "nao_texto"
    for m in d["linha_do_tempo"]:
        assert set(m) == {
            "remetente",
            "tipo",
            "em",
            "intencao",
            "intencao_confianca",
            "status_envio",
        }
    assert chaves_proibidas(d) == []
    assert SEGREDO_TEXTO not in r.text and SEGREDO_TEL not in r.text and "ext-1" not in r.text


async def test_conversa_de_outra_empresa_ou_inexistente_devolve_404(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID, tenant_b: uuid.UUID
) -> None:
    _, _ = await semear(db, tenant_a)
    cb, _ = await semear(db, tenant_b)
    slug_a = await slug_de(db, tenant_a)
    r = await admin_api.get(f"/admin/empresas/{slug_a}/conversas/{cb}")
    assert r.status_code == 404 and r.json()["codigo"] == "conversa_nao_encontrada"
    r = await admin_api.get(f"/admin/empresas/{slug_a}/conversas/{uuid.uuid4()}")
    assert r.status_code == 404
    r = await admin_api.get(f"/admin/empresas/{slug_a}/conversas/nao-e-uuid")
    assert r.status_code == 400
    assert (await admin_api.get("/admin/empresas/nao-existe/conversas")).status_code == 404


async def test_banco_recusa_ler_texto_e_contato_pelo_papel_do_painel(
    db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    await semear(db, tenant_a)
    for consulta in (
        "SELECT conteudo FROM messages",
        "SELECT contato_enc FROM conversations",
        "SELECT contato_hash FROM conversations",
        "SELECT * FROM messages",
        "SELECT external_id FROM messages",
        "SELECT m.* FROM messages m",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with painel_session() as s:
                await s.execute(text(consulta))


async def test_listar_exige_sessao(
    admin_api: AdminApi, db: AsyncEngine, tenant_a: uuid.UUID
) -> None:
    slug = await slug_de(db, tenant_a)
    assert (await admin_api.cliente.get(f"/admin/empresas/{slug}/conversas")).status_code == 401
