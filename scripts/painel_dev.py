"""Sobe a API com o login de desenvolvimento do painel (`make painel-dev`).

Só funciona em desenvolvimento: define `ENV=development` e `PAINEL_AUTH_MODE=dev` antes de importar a aplicação.
Se `OPERADORES` estiver vazio, entra como `dev@local` com papel de operação. Em produção use o login OIDC.
"""

from __future__ import annotations

import os

os.environ.setdefault("ENV", "development")
os.environ.setdefault("PAINEL_AUTH_MODE", "dev")
os.environ.setdefault("OPERADORES", "dev@local:operacao")


def main() -> None:
    import uvicorn

    from scripts.verificar_migracao import exigir_migracao_sincrono

    exigir_migracao_sincrono()

    print(
        "Painel: http://localhost:8000/painel/  (login de desenvolvimento, só com ENV=development)"
    )
    uvicorn.run("apps.api.main:app", reload=True, port=8000)


if __name__ == "__main__":
    main()
