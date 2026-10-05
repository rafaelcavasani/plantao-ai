"""Isolamento do papel administrativo: nenhum módulo de `apps/` usa `db.admin` nem `database_admin_url`
(research R-16; o papel administrativo ignora RLS e só pode ser usado por `scripts/` e `core/tenancy`,
quando recebe a sessão por parâmetro).
"""

from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2] / "apps"
PROIBIDOS = {"db.admin", "database_admin_url"}


def _nomes_importados(arquivo: Path) -> set[str]:
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
    nomes: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes.update(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module)
            nomes.update(f"{no.module}.{alias.name}" for alias in no.names)
        elif isinstance(no, ast.Attribute):
            nomes.add(no.attr)
    return nomes


def test_nenhum_arquivo_em_apps_importa_o_papel_administrativo() -> None:
    ofensores: list[str] = []
    for arquivo in RAIZ.rglob("*.py"):
        nomes = _nomes_importados(arquivo)
        if any(proibido in nome for nome in nomes for proibido in PROIBIDOS):
            ofensores.append(str(arquivo.relative_to(RAIZ.parent)))
    assert ofensores == [], f"apps/ usando o papel administrativo: {ofensores}"
