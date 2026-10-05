"""Schema da saída do Agente de Suporte (contrato em contracts/llm-contracts.md)."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SaidaSuporte(BaseModel):
    responde: bool
    confianca: float = Field(ge=0.0, le=1.0)
    resposta: str = Field(default="", max_length=600)
    trechos_usados: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _resposta_obrigatoria(self) -> SaidaSuporte:
        if self.responde and not self.resposta.strip():
            raise ValueError("responde=true exige resposta não vazia")
        return self
