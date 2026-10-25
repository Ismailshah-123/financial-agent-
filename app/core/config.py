"""
app.core.config
================
Single source of truth for all runtime configuration.

WHAT THIS FILE DOES
--------------------
Defines a `Settings` object (Pydantic v2 `BaseSettings`) that loads values
from environment variables / a `.env` file at process startup, validates
them, and exposes them as typed, IDE-autocompletable attributes. Settings
are grouped into nested sub-models (Database, Redis, Security, LLM, SAP,
etc.) so each subsystem only has to know about its own slice of config
instead of one giant flat namespace.

WHY IT IS STRUCTURED THIS WAY
------------------------------
- Nested sub-settings (`settings.database.url`, `settings.security.jwt_secret_key`)
  keep the object readable as the platform grows to dozens of agents and
  integrations, instead of collapsing into 150+ flat UPPER_CASE attributes.
- `@lru_cache` on `get_settings()` guarantees the .env file is parsed once
  per process, not on every import, and gives FastAPI a cheap dependency
  to inject (`Depends(get_settings)`) for testability (override in tests).
- A module-level `settings` singleton is also exported for the common case
  (scripts, Celery workers, Alembic env.py) where dependency injection
  isn't practical.
- `Environment` drives fail-fast validation: production refuses to boot
  with debug mode on, a default JWT secret, or permissive CORS.

HOW TO EXTEND
--------------
Adding a new integration (e.g. a new LLM provider or a new SAP endpoint)
means adding a field to the relevant sub-settings class below and to
`.env.example` — never sprinkling `os.getenv()` calls throughout the
codebase. If code outside this file calls `os.getenv` directly, that is
a bug.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# The .env file lives at the repository root. Resolving it from this file (instead of the current
# working directory) means the API, Alembic and the scripts all find the same file wherever they
# are started from. A missing file is fine: containers and CI set real environment variables.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _group_config(prefix: str) -> SettingsConfigDict:
    """Shared configuration for every settings group.

    Each group (database, security, SAP, ...) is its own `BaseSettings` class, and a nested
    group does NOT inherit the root class's `env_file`. Without `env_file` here, values in `.env`
    were silently ignored and only real environment variables took effect.

    `env_ignore_empty` makes blank lines such as `SAP_SERVICE_LAYER_URL=` (as in `.env.example`)
    behave as "not set" instead of failing validation as an empty URL.
    """
    return SettingsConfigDict(
        env_prefix=prefix,
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )



class Environment(str, Enum):
    """Deployment environment. Drives fail-fast safety checks at boot."""

    LOCAL = "local"
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class AppSettings(BaseSettings):
    """Top-level application identity and behaviour flags."""

    model_config = _group_config("APP_")

    name: str = "Finance AI Platform"
    environment: Environment = Environment.LOCAL
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    host: str = "0.0.0.0"
    port: int = 8000
    timezone: str = "UTC"
    # Comma-separated origins in env, parsed into a list.
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    request_timeout_seconds: int = 30
    # Number of reverse proxies we operate in front of the API (for example 1
    # when nginx fronts uvicorn). X-Forwarded-For is trusted only for that many
    # right-most entries; 0 means the header is ignored entirely.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection configuration (async SQLAlchemy + Alembic)."""

    model_config = _group_config("DB_")

    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: SecretStr = SecretStr("CHANGE_ME_IN_ENV")
    name: str = "finance_ai_db"
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout_seconds: int = 30
    echo_sql: bool = False

    @property
    def async_url(self) -> str:
        """URL used by the app at runtime (asyncpg driver)."""
        return (
            f"postgresql+asyncpg://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.name}"
        )

    @property
    def sync_url(self) -> str:
        """URL used by Alembic migrations (psycopg2, sync driver)."""
        return (
            f"postgresql+psycopg2://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.name}"
        )


class RedisSettings(BaseSettings):
    """Redis: caching, rate limiting, Celery result backend."""

    model_config = _group_config("REDIS_")

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: SecretStr | None = None
    use_tls: bool = False

    @property
    def url(self) -> str:
        scheme = "rediss" if self.use_tls else "redis"
        auth = f":{self.password.get_secret_value()}@" if self.password else ""
        return f"{scheme}://{auth}{self.host}:{self.port}/{self.db}"


class BrokerSettings(BaseSettings):
    """Message broker for the event bus / Celery task queue."""

    model_config = _group_config("BROKER_")

    # "rabbitmq" for Celery+approval workflows, "kafka" for high-throughput
    # domain event streaming. Both are supported behind the same interface;
    # see app/core/events.py.
    provider: Literal["rabbitmq", "kafka", "in_memory"] = "in_memory"
    url: str = "amqp://localhost:5672//"
    kafka_bootstrap_servers: str = "localhost:9092"


class QdrantSettings(BaseSettings):
    """Vector database for RAG / enterprise search / policy retrieval."""

    model_config = _group_config("QDRANT_")

    host: str = "localhost"
    port: int = 6333
    api_key: SecretStr | None = None
    use_https: bool = False
    collection_prefix: str = "finance_ai"


class SecuritySettings(BaseSettings):
    """JWT, password hashing, and other auth-related configuration."""

    model_config = _group_config("SECURITY_")

    jwt_secret_key: SecretStr = SecretStr("CHANGE_ME_IN_PRODUCTION")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    password_hash_scheme: str = "bcrypt"
    api_key_prefix: str = "fai_"
    mfa_issuer_name: str = "Finance AI Platform"
    allow_public_registration: bool = False
    # Azure AD / Google SSO — populated when SSO is enabled.
    azure_ad_tenant_id: str | None = None
    azure_ad_client_id: str | None = None
    azure_ad_client_secret: SecretStr | None = None
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None


class LLMSettings(BaseSettings):
    """Credentials and defaults for every model provider the agents can use."""

    model_config = _group_config("LLM_")

    default_provider: Literal["groq", "anthropic", "openai", "gemini"] = "groq"
    fallback_chain: list[str] = Field(
        default_factory=lambda: ["groq", "anthropic", "openai"]
    )

    groq_api_key: SecretStr | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-4-6"

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o"

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-1.5-pro"

    request_timeout_seconds: int = 60
    max_retries: int = 3


class SAPSettings(BaseSettings):
    """SAP Business One Service Layer / DI API connection (Phase 2+)."""

    model_config = _group_config("SAP_")

    enabled: bool = False
    service_layer_url: AnyHttpUrl | None = None
    company_db: str | None = None
    username: str | None = None
    password: SecretStr | None = None
    verify_ssl: bool = True
    default_cash_account_code: str | None = Field(
        default=None,
        description="SAP G/L account code (SAP's own chart of accounts — "
        "NOT this platform's internal app.services.posting_service "
        "account codes, which are a different chart entirely) used as "
        "the CashAccount/TransferAccount on synced payments. Required "
        "before any payment can sync to SAP; there is deliberately no "
        "default guessed here, since posting to the wrong G/L account "
        "is a real accounting error, not a cosmetic one.",
    )


class VoiceSettings(BaseSettings):
    """Voice AI stack (Phase 2+): STT/TTS/telephony providers."""

    model_config = _group_config("VOICE_")

    enabled: bool = False
    vapi_api_key: SecretStr | None = None
    deepgram_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None


class Settings(BaseSettings):
    """
    Root settings object. Composes every sub-settings group above.

    Access pattern used everywhere else in the codebase:
        from app.core.config import settings
        settings.database.async_url
        settings.security.jwt_secret_key.get_secret_value()
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app: AppSettings = Field(default_factory=AppSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    broker: BrokerSettings = Field(default_factory=BrokerSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    sap: SAPSettings = Field(default_factory=SAPSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)

    @model_validator(mode="after")
    def _validate_production_safety(self) -> "Settings":
        """Fail fast at boot if production is misconfigured, instead of
        discovering it in an incident review."""
        if self.sap.enabled and not self.sap.verify_ssl:
            raise ValueError("SAP_VERIFY_SSL must be true whenever SAP integration is enabled.")
        if self.app.environment == Environment.PRODUCTION:
            if self.app.debug:
                raise ValueError("APP_DEBUG must be false in production.")
            if self.security.jwt_secret_key.get_secret_value() == "CHANGE_ME_IN_PRODUCTION":
                raise ValueError("SECURITY_JWT_SECRET_KEY must be overridden in production.")
            if self.database.password.get_secret_value() == "CHANGE_ME_IN_ENV":
                raise ValueError("DB_PASSWORD must be overridden in production.")
            if "*" in self.app.cors_origins:
                raise ValueError("Wildcard CORS origins are not allowed in production.")
            if self.security.allow_public_registration:
                raise ValueError("SECURITY_ALLOW_PUBLIC_REGISTRATION must be false in production.")
        if self.app.environment in {Environment.PRODUCTION, Environment.STAGING}:
            if len(self.security.jwt_secret_key.get_secret_value()) < 32:
                raise ValueError(
                    "SECURITY_JWT_SECRET_KEY must be at least 32 characters outside local/test environments."
                )
        return self

    @property
    def is_production(self) -> bool:
        return self.app.environment == Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings factory. Use this via FastAPI's `Depends(get_settings)`
    in routes/services that need to be unit-testable with overridden config
    (`app.dependency_overrides[get_settings] = lambda: test_settings`).
    """
    return Settings()


# Module-level singleton for non-DI contexts (Celery workers, Alembic
# env.py, standalone scripts).
settings = get_settings()
