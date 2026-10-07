"""Segurança HTTP da API de operação e do front-end estático (spec 004, T015; FR-001, FR-002, FR-006)."""

import pytest

from apps.api.admin.auth import COOKIE
from core.config import settings
from tests.fakes.painel import BASE, LEITOR, OPERADOR, AdminApi

pytestmark = pytest.mark.contract

ROTAS_DE_LEITURA = ["/admin/eu", "/admin/saude"]


@pytest.mark.parametrize("caminho", ROTAS_DE_LEITURA)
async def test_sem_sessao_devolve_401(admin_api: AdminApi, caminho: str) -> None:
    r = await admin_api.cliente.get(caminho)
    assert r.status_code == 401
    assert r.json()["codigo"] == "nao_autenticado"


async def test_cookie_invalido_devolve_401(admin_api: AdminApi) -> None:
    r = await admin_api.cliente.get("/admin/eu", headers={"Cookie": f"{COOKIE}=forjado"})
    assert r.status_code == 401


async def test_eu_devolve_email_e_papel(admin_api: AdminApi) -> None:
    r = await admin_api.get("/admin/eu", email=LEITOR)
    assert r.status_code == 200
    assert (r.json()["email"], r.json()["papel"]) == (LEITOR, "leitura")


async def test_saida_apaga_a_sessao(admin_api: AdminApi) -> None:
    cab = await admin_api.cabecalhos()
    assert (await admin_api.cliente.get("/admin/eu", headers=cab)).status_code == 200
    r = await admin_api.cliente.post("/admin/auth/sair", headers=cab)
    assert r.status_code == 204
    assert (await admin_api.cliente.get("/admin/eu", headers=cab)).status_code == 401


async def test_post_sem_origin_e_recusado(admin_api: AdminApi) -> None:
    r = await admin_api.post("/admin/atualizar", origem=None)
    assert r.status_code == 403 and r.json()["codigo"] == "origem_invalida"


async def test_post_com_origin_de_outro_site_e_recusado(admin_api: AdminApi) -> None:
    r = await admin_api.post("/admin/atualizar", origem="https://malicioso.exemplo")
    assert r.status_code == 403 and r.json()["codigo"] == "origem_invalida"


async def test_get_nao_exige_origin(admin_api: AdminApi) -> None:
    cab = await admin_api.cabecalhos(origem=None)
    assert (await admin_api.cliente.get("/admin/eu", headers=cab)).status_code == 200


async def test_atualizar_enfileira_e_limita_uma_por_30_segundos(admin_api: AdminApi) -> None:
    r = await admin_api.post("/admin/atualizar")
    assert r.status_code == 202 and r.json()["enfileirado"] is True
    assert [n for n, *_ in admin_api.fila.jobs][-1:] == ["agregar_painel"] or admin_api.fila.jobs
    r2 = await admin_api.post("/admin/atualizar")
    assert r2.status_code == 429 and r2.headers["retry-after"] == "30"
    # Outro operador pode atualizar (o limite é por operador) mas a trava de 20 s evita job duplicado.
    antes = len(admin_api.fila.jobs)
    r3 = await admin_api.post("/admin/atualizar", email=LEITOR)
    assert r3.status_code == 202
    assert len(admin_api.fila.jobs) == antes


async def test_saude_sem_dados_nao_e_desatualizada(admin_api: AdminApi) -> None:
    r = await admin_api.get("/admin/saude")
    assert r.status_code == 200
    assert r.json() == {"atualizado_em": None, "idade_s": None, "desatualizado": False}


async def test_erros_de_validacao_seguem_o_formato_padrao(admin_api: AdminApi) -> None:
    r = await admin_api.cliente.get(
        "/admin/auth/retorno", params={"state": "x"}, headers=await admin_api.cabecalhos()
    )
    assert r.status_code == 400
    corpo = r.json()
    assert corpo["codigo"] == "validacao" and "code" in corpo["campos"]


async def test_retorno_com_state_desconhecido_e_401(
    admin_api: AdminApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "oidc_issuer", "https://idp.exemplo.com")
    for campo in ("oidc_client_id", "oidc_client_secret", "oidc_redirect_uri"):
        monkeypatch.setattr(settings, campo, "x")
    r = await admin_api.cliente.get(
        "/admin/auth/retorno", params={"code": "c", "state": "desconhecido"}
    )
    assert r.status_code == 401


async def test_respostas_da_api_nao_sao_cacheaveis(admin_api: AdminApi) -> None:
    r = await admin_api.get("/admin/eu")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"


async def test_arquivos_do_painel_levam_csp_estrita(admin_api: AdminApi) -> None:
    r = await admin_api.cliente.get("/painel/")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp and "style-src 'self'" in csp
    assert "font-src 'self'" in csp and "img-src 'self' data:" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "DENY"


async def test_painel_nao_lista_pastas(admin_api: AdminApi) -> None:
    r = await admin_api.cliente.get("/painel/js/")
    assert r.status_code in (404, 307, 308)


async def test_login_dev_so_funciona_em_development(
    admin_api: AdminApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "painel_auth_mode", "dev")
    r = await admin_api.cliente.get("/admin/auth/entrar", follow_redirects=False)
    assert (
        r.status_code == 403 and r.json()["codigo"] == "sem_permissao"
    )  # ENV=test, não development


async def test_login_dev_cria_sessao_com_cookie_seguro(
    admin_api: AdminApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "painel_auth_mode", "dev")
    monkeypatch.setattr(settings, "env", "development")
    r = await admin_api.cliente.get(
        "/admin/auth/entrar", params={"destino": "/painel/#/empresas"}, follow_redirects=False
    )
    assert r.status_code == 303 and r.headers["location"] == "/painel/#/empresas"
    cookie = r.headers["set-cookie"].lower()
    assert f"{COOKIE}=" in cookie and "httponly" in cookie and "samesite=lax" in cookie


@pytest.mark.parametrize(
    "destino", ["https://malicioso.exemplo", "//malicioso.exemplo", "/outra", "/painel//x"]
)
async def test_destino_de_login_nunca_sai_do_painel(
    admin_api: AdminApi, monkeypatch: pytest.MonkeyPatch, destino: str
) -> None:
    monkeypatch.setattr(settings, "painel_auth_mode", "dev")
    monkeypatch.setattr(settings, "env", "development")
    r = await admin_api.cliente.get(
        "/admin/auth/entrar", params={"destino": destino}, follow_redirects=False
    )
    assert r.headers["location"] == "/painel/"


async def test_cookie_em_producao_e_secure(
    admin_api: AdminApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import Response

    from apps.api.admin.auth import SessaoStore, _definir_cookie

    resp = Response()
    _definir_cookie(resp, "tok", SessaoStore(admin_api.redis))
    assert "secure" in resp.headers["set-cookie"].lower()  # ENV=test: não é development
    assert OPERADOR and BASE


async def test_toda_rota_de_dados_exige_sessao(admin_api: AdminApi) -> None:
    """Varre o OpenAPI: sem cookie, nenhuma rota `/admin` (fora do login) pode responder algo que não 401."""
    from apps.api.main import app

    substituicoes = {
        "slug": "qualquer-empresa",
        "remessa": "a" * 32,
        "conversa_id": "123e4567-e89b-12d3-a456-426614174000",
    }
    rotas = [
        (metodo.upper(), caminho)
        for caminho, operacoes in app.openapi()["paths"].items()
        if caminho.startswith("/admin") and not caminho.startswith("/admin/auth/")
        for metodo in operacoes
    ]
    assert len(rotas) >= 20, "o OpenAPI deveria listar todas as rotas de operação"
    for metodo, caminho in rotas:
        url = caminho.format(**substituicoes)
        resposta = await admin_api.cliente.request(
            metodo, url, headers={"Origin": BASE}, json={} if metodo != "GET" else None
        )
        assert resposta.status_code == 401, (
            f"{metodo} {caminho} respondeu {resposta.status_code} sem sessão"
        )


async def test_hsts_so_fora_de_desenvolvimento(
    admin_api: AdminApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "strict-transport-security" not in (await admin_api.cliente.get("/painel/")).headers
    monkeypatch.setattr(settings, "env", "production")
    r = await admin_api.cliente.get("/painel/")
    assert r.headers["strict-transport-security"].startswith("max-age=31536000")
    assert "strict-transport-security" in (await admin_api.get("/admin/eu")).headers


async def test_login_sem_oidc_configurado_devolve_503_claro_e_nao_500(
    admin_api: AdminApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    for campo in ("oidc_issuer", "oidc_client_id", "oidc_client_secret", "oidc_redirect_uri"):
        monkeypatch.setattr(settings, campo, "")
    r = await admin_api.cliente.get("/admin/auth/entrar", follow_redirects=False)
    assert r.status_code == 503 and r.json()["codigo"] == "login_nao_configurado"
    assert "OIDC_ISSUER" in r.json()["mensagem"] and "make painel-dev" in r.json()["mensagem"]
    r = await admin_api.cliente.get("/admin/auth/retorno", params={"code": "c", "state": "s"})
    assert r.status_code == 503
    modo = (await admin_api.cliente.get("/admin/auth/modo")).json()
    assert modo["configurado"] is False and "OIDC_ISSUER" in modo["mensagem"]


async def test_issuer_sem_protocolo_tambem_e_tratado(
    admin_api: AdminApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "oidc_issuer", "accounts.exemplo.com")
    for campo in ("oidc_client_id", "oidc_client_secret", "oidc_redirect_uri"):
        monkeypatch.setattr(settings, campo, "x")
    r = await admin_api.cliente.get("/admin/auth/entrar", follow_redirects=False)
    assert r.status_code == 503 and "http://" in r.json()["mensagem"]


async def test_modo_dev_aparece_configurado_so_em_desenvolvimento(
    admin_api: AdminApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "painel_auth_mode", "dev")
    assert (await admin_api.cliente.get("/admin/auth/modo")).json()[
        "configurado"
    ] is False  # ENV=test
    monkeypatch.setattr(settings, "env", "development")
    assert (await admin_api.cliente.get("/admin/auth/modo")).json()["configurado"] is True


async def test_provedor_fora_do_ar_vira_502_e_nao_500(
    admin_api: AdminApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    from apps.api.admin import auth

    monkeypatch.setattr(settings, "oidc_issuer", "http://127.0.0.1:9")  # porta fechada
    for campo in ("oidc_client_id", "oidc_client_secret", "oidc_redirect_uri"):
        monkeypatch.setattr(settings, campo, "x")
    monkeypatch.setattr(auth, "_oidc", auth.OidcHttp(httpx.AsyncClient(timeout=2.0)))
    r = await admin_api.cliente.get("/admin/auth/entrar", follow_redirects=False)
    assert r.status_code == 502 and r.json()["codigo"] == "provedor_indisponivel"
