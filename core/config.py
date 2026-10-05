"""Configurações centrais da aplicação Plantão.AI.

Carrega variáveis de ambiente usando pydantic-settings. Todas as outras
partes do sistema devem importar `settings` a partir deste módulo, em vez
de ler `os.environ` diretamente.
"""

from __future__ import annotations

import uuid
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Ambiente
    env: str = "development"
    log_level: str = "INFO"

    # Banco de dados. `database_url` usa o papel `plantao_app` (sujeito a RLS);
    # `database_admin_url` é o dono do banco, usado só por migrações e seed.
    database_url: str = "postgresql+asyncpg://plantao_app:plantao_app@localhost:5432/plantao"
    database_admin_url: str = "postgresql+asyncpg://plantao:plantao@localhost:5432/plantao"
    app_db_password: str = "plantao_app"  # senha do papel plantao_app criada pela migração 0003
    redis_url: str = "redis://localhost:6379/0"

    # Empresa piloto (Sprint 2: um único tenant fixo)
    pilot_tenant_id: str = ""

    # Modelos de IA (via OpenRouter como gateway — ver seção 8.2)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    model_cheap: str = "anthropic/claude-3-haiku"
    model_strong: str = "anthropic/claude-3.5-sonnet"
    embedding_model: str = "openai/text-embedding-3-small"
    llm_timeout_seconds: float = 15.0

    # Observabilidade
    langsmith_api_key: str = ""
    langsmith_project: str = "plantao-ai"

    # WhatsApp
    whatsapp_provider: str = "evolution"  # evolution | meta_cloud | twilio | zapi
    whatsapp_base_url: str = "http://localhost:8080"
    whatsapp_api_key: str = ""
    whatsapp_instance: str = "plantao"
    whatsapp_verify_token: str = "change-me"
    whatsapp_webhook_secret: str = ""

    # Segurança e PII
    pii_encryption_key: str = ""
    pii_hash_key: str = ""

    # Limites e tempos
    rate_limit_msgs_per_min: int = 60
    handoff_ttl_minutes: int = 60
    conversation_reuse_hours: int = 24

    # Guardrails padrão (podem ser sobrescritos por tenant em tenant_config)
    default_confidence_threshold: float = 0.7

    def tenant_piloto(self) -> uuid.UUID:
        """Id do tenant piloto. Levanta RuntimeError se ausente ou inválido."""
        try:
            return uuid.UUID(self.pilot_tenant_id)
        except ValueError as exc:
            raise RuntimeError(
                "PILOT_TENANT_ID ausente ou inválido. Rode `python -m scripts.seed_tenant` "
                "e copie o id impresso para o .env."
            ) from exc

    def exigir_segredos(self) -> None:
        """Falha na inicialização se algum segredo obrigatório estiver ausente."""
        obrigatorios = {
            "PII_ENCRYPTION_KEY": self.pii_encryption_key,
            "PII_HASH_KEY": self.pii_hash_key,
            "WHATSAPP_WEBHOOK_SECRET": self.whatsapp_webhook_secret,
        }
        ausentes = [nome for nome, valor in obrigatorios.items() if not valor]
        if ausentes:
            raise RuntimeError(
                f"Variáveis de ambiente obrigatórias ausentes: {', '.join(ausentes)}"
            )


@lru_cache
def get_settings() -> Settings:
    """Retorna uma instância cacheada das configurações."""
    return Settings()


settings = get_settings()
