"""Isolamento do papel administrativo: nenhum módulo de `apps/` usa `db.admin` nem `database_admin_url`
(research R-16; o papel administrativo ignora RLS e só pode ser usado por `scripts/` e `core/tenancy`,
quando recebe a sessão por parâmetro).

Exceção única, decidida no ADR-0006 e imposta também pelo import-linter: `apps/api/admin/escrita.py`, o módulo das
rotas de escrita do painel (spec 004). Qualquer outro arquivo de `apps/` continua proibido.
"""

from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2] / "apps"
PROIBIDOS = {"db.admin", "database_admin_url"}
PERMITIDOS = {Path("apps/api/admin/escrita.py")}  # ADR-0006


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
    ofensores: list[Path] = []
    for arquivo in RAIZ.rglob("*.py"):
        nomes = _nomes_importados(arquivo)
        if any(proibido in nome for nome in nomes for proibido in PROIBIDOS):
            ofensores.append(arquivo.relative_to(RAIZ.parent))
    assert {o for o in ofensores if o not in PERMITIDOS} == set(), (
        f"apps/ usando o papel administrativo fora do módulo permitido: {ofensores}"
    )
    assert set(ofensores) <= PERMITIDOS
