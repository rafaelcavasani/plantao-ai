"""Autenticação do operador do painel (ADR-0007; research R-06).

- Login por OIDC (código de autorização + PKCE, `state` e `nonce`), validando o `id_token` com PyJWT.
- Quem pode entrar e com qual papel vem de `OPERADORES` (`email:papel,email:papel`).
- Sessão opaca de 256 bits guardada no Redis só como `sha256` do token, com expiração deslizante por
  inatividade e teto absoluto (FR-006). Cookie `HttpOnly; Secure; SameSite=Lax`.
- `PAINEL_AUTH_MODE=dev` entra com um operador fixo e só é aceito com `ENV=development`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Annotated, Any, Protocol, cast
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from jwt.algorithms import RSAAlgorithm
from redis.asyncio import Redis

from apps.api.admin.schemas import ErroAdmin, Operador, Papel
from apps.api.deps import get_redis
from core.config import settings
from core.observability.logging import definir_contexto

COOKIE = "plantao_painel"
PAPEIS: tuple[Papel, ...] = ("leitura", "operacao")
PREFIXO_SESSAO = "painel:sessao:"
PREFIXO_OIDC = "painel:oidc:"
VALIDADE_OIDC_SEGUNDOS = 600
OPERADOR_DEV = "dev@local"

router = APIRouter(tags=["admin-auth"])


# --- Operadores autorizados ---------------------------------------------------------------------


def parse_operadores(texto: str) -> dict[str, Papel]:
    """`email:papel,email:papel` → `{email: papel}`. Papel desconhecido é erro de configuração."""
    resultado: dict[str, Papel] = {}
    for item in (parte.strip() for parte in texto.split(",")):
        if not item:
            continue
        email, _, papel = item.rpartition(":")
        email = email.strip().lower()
        papel = papel.strip().lower()
        if not email or "@" not in email or papel not in PAPEIS:
            raise ValueError(
                "OPERADORES inválido: use 'email:papel' com papel 'leitura' ou 'operacao'."
            )
        resultado[email] = papel
    return resultado


def operadores_autorizados() -> dict[str, Papel]:
    return parse_operadores(settings.operadores)


# --- Sessão no Redis ----------------------------------------------------------------------------


def _chave(token: str) -> str:
    return PREFIXO_SESSAO + hashlib.sha256(token.encode()).hexdigest()


class SessaoStore:
    """Sessões do painel. O token só existe no cookie; o Redis guarda o hash dele."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @property
    def inatividade_s(self) -> int:
        return settings.painel_sessao_inatividade_min * 60

    @property
    def maxima_s(self) -> int:
        return settings.painel_sessao_maxima_h * 3600

    async def criar(self, email: str, papel: Papel, *, agora: float | None = None) -> str:
        token = secrets.token_urlsafe(32)
        t = time.time() if agora is None else agora
        dados = {"email": email, "papel": papel, "criada_em": t, "ultima": t}
        await self._redis.set(_chave(token), json.dumps(dados), ex=self.inatividade_s)
        return token

    async def obter(self, token: str | None, *, agora: float | None = None) -> Operador | None:
        """Devolve o operador e renova a inatividade; `None` se não existe, expirou ou perdeu o papel."""
        if not token:
            return None
        bruto = await self._redis.get(_chave(token))
        if bruto is None:
            return None
        dados = json.loads(bruto)
        t = time.time() if agora is None else agora
        if t - float(dados["criada_em"]) > self.maxima_s:
            await self._redis.delete(_chave(token))
            return None
        if t - float(dados["ultima"]) > self.inatividade_s:
            await self._redis.delete(_chave(token))
            return None
        # A lista de operadores manda: quem saiu dela perde a sessão, e o papel acompanha a lista.
        papel = operadores_autorizados().get(dados["email"])
        if papel is None and not (
            settings.painel_auth_mode == "dev" and dados["email"] == OPERADOR_DEV
        ):
            await self._redis.delete(_chave(token))
            return None
        papel = papel or cast(Papel, dados["papel"])
        dados["ultima"] = t
        dados["papel"] = papel
        await self._redis.set(_chave(token), json.dumps(dados), ex=self.inatividade_s)
        return Operador(dados["email"], papel, expira_em=t + self.inatividade_s)

    async def apagar(self, token: str | None) -> None:
        if token:
            await self._redis.delete(_chave(token))


# --- OIDC ---------------------------------------------------------------------------------------


class ClienteOidc(Protocol):
    """Contrato mínimo do provedor de identidade (substituível nos testes)."""

    async def url_autorizacao(self, state: str, nonce: str, desafio: str) -> str: ...

    async def validar_retorno(
        self, codigo: str, verificador: str, nonce: str
    ) -> dict[str, Any]: ...


def desafio_pkce(verificador: str) -> str:
    digest = hashlib.sha256(verificador.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def validar_id_token(
    id_token: str, *, jwks: dict[str, Any], issuer: str, audience: str, nonce: str
) -> dict[str, Any]:
    """Valida assinatura (RS256 pelas chaves do provedor), `iss`, `aud`, `exp`, `nonce` e e-mail verificado."""
    try:
        kid = jwt.get_unverified_header(id_token).get("kid")
        chave = next(
            (
                RSAAlgorithm.from_jwk(json.dumps(k))
                for k in jwks.get("keys", [])
                if k.get("kid") == kid
            ),
            None,
        )
        if chave is None:
            raise ErroAdmin(401, "nao_autenticado", "Chave do provedor desconhecida.")
        claims = jwt.decode(
            id_token,
            chave,  # type: ignore[arg-type]
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise ErroAdmin(401, "nao_autenticado", "Não foi possível validar o login.") from exc
    if claims.get("nonce") != nonce:
        raise ErroAdmin(401, "nao_autenticado", "Não foi possível validar o login.")
    if not claims.get("email") or claims.get("email_verified") is not True:
        raise ErroAdmin(403, "operador_nao_autorizado", "E-mail não verificado pelo provedor.")
    return claims


def exigir_oidc_configurado() -> None:
    """Sem provedor configurado não há como entrar: devolve 503 com a instrução, nunca um 500 com stack trace."""
    faltando = [
        nome
        for nome, valor in (
            ("OIDC_ISSUER", settings.oidc_issuer),
            ("OIDC_CLIENT_ID", settings.oidc_client_id),
            ("OIDC_CLIENT_SECRET", settings.oidc_client_secret),
            ("OIDC_REDIRECT_URI", settings.oidc_redirect_uri),
        )
        if not valor.strip()
    ]
    if faltando or not settings.oidc_issuer.startswith(("http://", "https://")):
        raise ErroAdmin(
            503,
            "login_nao_configurado",
            "O login do painel não está configurado. Defina "
            + ", ".join(faltando or ["OIDC_ISSUER (com http:// ou https://)"])
            + " ou, em desenvolvimento, rode `make painel-dev` (PAINEL_AUTH_MODE=dev com ENV=development).",
        )


class OidcHttp:
    """Cliente OIDC real: descoberta, troca do código e JWKS por `httpx` (com timeout)."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http or httpx.AsyncClient(timeout=10.0)
        self._descoberta: dict[str, Any] | None = None
        self._jwks: tuple[float, dict[str, Any]] | None = None

    async def fechar(self) -> None:
        await self._http.aclose()

    async def _config(self) -> dict[str, Any]:
        if self._descoberta is None:
            url = settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
            try:
                resposta = await self._http.get(url)
                resposta.raise_for_status()
                self._descoberta = resposta.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise ErroAdmin(
                    502, "provedor_indisponivel", "Não foi possível falar com o provedor de login."
                ) from exc
        return self._descoberta or {}

    async def _chaves(self) -> dict[str, Any]:
        agora = time.time()
        if self._jwks is None or agora - self._jwks[0] > 600:
            resposta = await self._http.get((await self._config())["jwks_uri"])
            resposta.raise_for_status()
            self._jwks = (agora, resposta.json())
        return self._jwks[1]

    async def url_autorizacao(self, state: str, nonce: str, desafio: str) -> str:
        parametros = {
            "response_type": "code",
            "client_id": settings.oidc_client_id,
            "redirect_uri": settings.oidc_redirect_uri,
            "scope": "openid email",
            "state": state,
            "nonce": nonce,
            "code_challenge": desafio,
            "code_challenge_method": "S256",
        }
        return str((await self._config())["authorization_endpoint"]) + "?" + urlencode(parametros)

    async def validar_retorno(self, codigo: str, verificador: str, nonce: str) -> dict[str, Any]:
        try:
            resposta = await self._http.post(
                (await self._config())["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": codigo,
                    "redirect_uri": settings.oidc_redirect_uri,
                    "client_id": settings.oidc_client_id,
                    "client_secret": settings.oidc_client_secret,
                    "code_verifier": verificador,
                },
            )
            resposta.raise_for_status()
            id_token = resposta.json()["id_token"]
            jwks = await self._chaves()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ErroAdmin(401, "nao_autenticado", "Não foi possível concluir o login.") from exc
        return validar_id_token(
            id_token,
            jwks=jwks,
            issuer=settings.oidc_issuer,
            audience=settings.oidc_client_id,
            nonce=nonce,
        )


_oidc: OidcHttp | None = None


async def fechar_oidc() -> None:
    """Fecha o cliente HTTP do provedor de identidade (chamado no desligamento da API)."""
    global _oidc
    if _oidc is not None:
        await _oidc.fechar()
        _oidc = None


def get_oidc() -> ClienteOidc:
    global _oidc  # cliente HTTP reaproveitado entre requisições (cache de descoberta e JWKS)
    if _oidc is None:
        _oidc = OidcHttp()
    return _oidc


# --- Dependências -------------------------------------------------------------------------------


def get_sessoes(redis: Annotated[Redis, Depends(get_redis)]) -> SessaoStore:
    return SessaoStore(redis)


Sessoes = Annotated[SessaoStore, Depends(get_sessoes)]


async def operador_atual(request: Request, sessoes: Sessoes) -> Operador:
    """Exige sessão válida (401 `nao_autenticado` caso contrário) e a renova."""
    operador = await sessoes.obter(request.cookies.get(COOKIE))
    if operador is None:
        raise ErroAdmin(401, "nao_autenticado", "Entre para continuar.")
    request.state.operador = operador
    definir_contexto(operador=operador.email, rota=request.url.path)
    return operador


async def exigir_operacao(operador: Annotated[Operador, Depends(operador_atual)]) -> Operador:
    if not operador.pode_operar:
        raise ErroAdmin(403, "sem_permissao", "O papel de leitura não permite esta ação.")
    return operador


OperadorAtual = Annotated[Operador, Depends(operador_atual)]
OperadorDeOperacao = Annotated[Operador, Depends(exigir_operacao)]


def _definir_cookie(resposta: Response, token: str, sessoes: SessaoStore) -> None:
    resposta.set_cookie(
        COOKIE,
        token,
        max_age=sessoes.maxima_s,
        httponly=True,
        secure=settings.env != "development",
        samesite="lax",
        path="/",
    )


def _destino_seguro(destino: str | None) -> str:
    """Só volta para dentro do painel (evita redirecionamento aberto)."""
    if (
        destino
        and destino.startswith("/painel/")
        and "//" not in destino[1:]
        and "\\" not in destino
    ):
        return destino
    return "/painel/"


# --- Rotas --------------------------------------------------------------------------------------


@router.get("/auth/modo")
async def modo_de_login() -> dict[str, Any]:
    """Diz à tela de login se dá para entrar (sem expor nenhum valor de configuração)."""
    try:
        if settings.painel_auth_mode == "dev":
            if settings.env != "development":
                raise ErroAdmin(403, "sem_permissao", "Modo de desenvolvimento desativado.")
        else:
            exigir_oidc_configurado()
    except ErroAdmin as erro:
        return {"modo": settings.painel_auth_mode, "configurado": False, "mensagem": erro.mensagem}
    return {"modo": settings.painel_auth_mode, "configurado": True, "mensagem": None}


@router.get("/auth/entrar")
async def entrar(
    sessoes: Sessoes,
    redis: Annotated[Redis, Depends(get_redis)],
    oidc: Annotated[ClienteOidc, Depends(get_oidc)],
    destino: Annotated[str | None, Query()] = None,
) -> Response:
    if settings.painel_auth_mode == "dev":
        if settings.env != "development":
            raise ErroAdmin(403, "sem_permissao", "Modo de desenvolvimento desativado.")
        autorizados = operadores_autorizados()
        email, papel = next(iter(autorizados.items()), (OPERADOR_DEV, "operacao"))
        token = await sessoes.criar(email, papel)
        resposta = RedirectResponse(_destino_seguro(destino), status_code=303)
        _definir_cookie(resposta, token, sessoes)
        return resposta
    exigir_oidc_configurado()
    state, nonce, verificador = (secrets.token_urlsafe(24) for _ in range(3))
    await redis.set(
        PREFIXO_OIDC + state,
        json.dumps(
            {"nonce": nonce, "verificador": verificador, "destino": _destino_seguro(destino)}
        ),
        ex=VALIDADE_OIDC_SEGUNDOS,
    )
    url = await oidc.url_autorizacao(state, nonce, desafio_pkce(verificador))
    return RedirectResponse(url, status_code=303)


@router.get("/auth/retorno")
async def retorno(
    sessoes: Sessoes,
    redis: Annotated[Redis, Depends(get_redis)],
    oidc: Annotated[ClienteOidc, Depends(get_oidc)],
    code: Annotated[str, Query(min_length=1)],
    state: Annotated[str, Query(min_length=1)],
) -> Response:
    exigir_oidc_configurado()
    bruto = await redis.getdel(PREFIXO_OIDC + state)  # uso único
    if bruto is None:
        raise ErroAdmin(401, "nao_autenticado", "Login expirado. Tente entrar de novo.")
    guardado = json.loads(bruto)
    claims = await oidc.validar_retorno(code, guardado["verificador"], guardado["nonce"])
    email = str(claims["email"]).lower()
    papel = operadores_autorizados().get(email)
    if papel is None:
        raise ErroAdmin(403, "operador_nao_autorizado", "Este e-mail não tem acesso ao painel.")
    token = await sessoes.criar(email, papel)
    resposta = RedirectResponse(_destino_seguro(guardado.get("destino")), status_code=303)
    _definir_cookie(resposta, token, sessoes)
    return resposta


@router.post("/auth/sair", status_code=204)
async def sair(request: Request, sessoes: Sessoes) -> Response:
    await sessoes.apagar(request.cookies.get(COOKIE))
    resposta = Response(status_code=204)
    resposta.delete_cookie(COOKIE, path="/")
    return resposta


@router.get("/eu")
async def eu(operador: OperadorAtual) -> dict[str, Any]:
    return {
        "email": operador.email,
        "papel": operador.papel,
        "expira_em": operador.expira_em,
    }
