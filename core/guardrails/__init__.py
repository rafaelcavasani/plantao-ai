"""Camada transversal de guardrails (ver seção 8.4 de Projeto_Empresa_Autonoma.md).

- `input_checks.checar_entrada`: antes de qualquer LLM.
- `output_checks.checar_saida`: antes de qualquer envio ao cliente final.
"""

from core.guardrails.base import ResultadoGuardrail
from core.guardrails.input_checks import checar_entrada
from core.guardrails.output_checks import ConfigGuardrails, checar_saida

__all__ = ["ConfigGuardrails", "ResultadoGuardrail", "checar_entrada", "checar_saida"]
