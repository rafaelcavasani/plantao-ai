"""Schema da saída do Agente Roteador (contrato em contracts/llm-contracts.md)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class Intencao(StrEnum):
    VENDA = "venda"
    SUPORTE = "suporte"
    AGENDAMENTO = "agendamento"
    COBRANCA = "cobranca"
    OUTRO = "outro"


class SaidaRoteador(BaseModel):
    intencao: Intencao
    confianca: float = Field(ge=0.0, le=1.0)
    intencoes_secundarias: list[Intencao] = Field(default_factory=list)

    @field_validator("intencoes_secundarias", mode="before")
    @classmethod
    def _aceita_nulo(cls, valor: object) -> object:
        return [] if valor is None else valor

    @model_validator(mode="after")
    def _limpar_secundarias(self) -> SaidaRoteador:
        """Remove a intenção principal e repetições, preservando a ordem."""
        vistas: list[Intencao] = []
        for item in self.intencoes_secundarias:
            if item != self.intencao and item not in vistas:
                vistas.append(item)
        self.intencoes_secundarias = vistas
        return self
