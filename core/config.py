"""Configurações centrais da aplicação Plantão.AI.

Carrega variáveis de ambiente usando pydantic-settings. Todas as outras
partes do sistema devem importar `settings` a partir deste módulo, em vez
de ler `os.environ` diretamente.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Ambiente
    env: str = "development"
    log_level: str = "INFO"

    # Banco de dados. `database_url` usa o papel `plantao_app` (sujeito a RLS);
    # `database_admin_url` é o dono do banco, usado só por migrações e pelos comandos do operador.
    database_url: str = "postgresql+asyncpg://plantao_app:plantao_app@localhost:5432/plantao"
    database_admin_url: str = "postgresql+asyncpg://plantao:plantao@localhost:5432/plantao"
    app_db_password: str = "plantao_app"  # senha do papel plantao_app criada pela migração 0003
    redis_url: str = "redis://localhost:6379/0"

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
    whatsapp_verify_token: str = "change-me"

    # Segurança e PII
    pii_encryption_key: str = ""
    pii_hash_key: str = ""

    # Limites e tempos
    conversation_reuse_hours: int = 24

    # Exclusão de dados de empresa: espera antes de apagar, para o worker terminar o que está em curso
    purge_drenagem_segundos: int = 120
    # Painel de operação (spec 004). `database_painel_url` usa o papel `plantao_painel` (só leitura,
    # sem acesso ao conteúdo das mensagens, ao contato nem às credenciais).
    database_painel_url: str = (
        "postgresql+asyncpg://plantao_painel:plantao_painel@localhost:5432/plantao"
    )
    painel_db_password: str = "plantao_painel"  # senha do papel criada pela migração 0005
    operadores: str = ""  # "email:papel,email:papel"; papel = leitura | operacao
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    painel_auth_mode: str = "oidc"  # oidc | dev (dev só com ENV=development)
    painel_sessao_inatividade_min: int = 30
    painel_sessao_maxima_h: int = 12
    painel_limite_silencio_horas: int = 24
    painel_limite_handoff_pct: float = 30.0
    painel_limite_custo_pct: float = 90.0
    painel_escrita_por_minuto: int = 60

    # Guardrails padrão (podem ser sobrescritos por tenant em tenant_config)
    default_confidence_threshold: float = 0.7

    def exigir_segredos(self) -> None:
        """Falha na inicialização se algum segredo obrigatório estiver ausente."""
        obrigatorios = {
            "PII_ENCRYPTION_KEY": self.pii_encryption_key,
            "PII_HASH_KEY": self.pii_hash_key,
        }
        if self.painel_auth_mode not in ("oidc", "dev"):
            raise RuntimeError("PAINEL_AUTH_MODE deve ser 'oidc' ou 'dev'.")
        if self.painel_auth_mode == "dev" and self.env != "development":
            raise RuntimeError("PAINEL_AUTH_MODE=dev só é permitido com ENV=development.")
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
