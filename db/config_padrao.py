"""Modelo padrão de configuração de uma empresa nova (research R-07).

`CONFIG_PADRAO` é o valor de referência; `nova_config_padrao()` devolve cópias, para que editar a
configuração de uma empresa nunca altere o modelo nem outra empresa (FR-008).
"""

from __future__ import annotations

import copy
from typing import Any, Final

PALAVRAS_GATILHO_PADRAO: Final = ["processo", "procon", "cancelar tudo", "advogado", "reclamação"]

CONFIG_PADRAO: Final[dict[str, Any]] = {
    "tom_de_voz": "",
    "horario_funcionamento": {},
    "limite_desconto_percentual": 0.0,
    "topicos_proibidos": [],
    "confianca_minima_handoff": 0.7,
    "palavras_gatilho": list(PALAVRAS_GATILHO_PADRAO),
    "router_confidence_threshold": 0.6,
    "min_similarity": 0.30,
    "handoff_ttl_minutos": 60,
    "limite_mensagens_por_minuto": 60,
}


def nova_config_padrao() -> dict[str, Any]:
    """Cópia profunda do modelo padrão (listas e dicionários novos)."""
    return copy.deepcopy(CONFIG_PADRAO)
