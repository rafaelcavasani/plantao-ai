"""API de operação do painel (`/admin/*`; contrato em specs/004-admin-dashboard/contracts/admin-api.md).

`router` monta autenticação, leitura, atualização e escrita sob `/admin`. Toda rota que altera estado passa
antes pela verificação de `Origin`. `registrar_erros` instala o erro padrão `{codigo, mensagem, campos}`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.admin import atualizar, escrita, leitura
from apps.api.admin.auth import fechar_oidc
from apps.api.admin.auth import router as auth_router
from apps.api.admin.schemas import registrar_erros
from apps.api.admin.seguranca import CabecalhosDeSeguranca, PainelEstatico, verificar_origem

router = APIRouter(prefix="/admin", dependencies=[Depends(verificar_origem)])
router.include_router(auth_router)
router.include_router(leitura.router)
router.include_router(atualizar.router)
router.include_router(escrita.router)

__all__ = ["CabecalhosDeSeguranca", "PainelEstatico", "fechar_oidc", "registrar_erros", "router"]
