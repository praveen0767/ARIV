try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except Exception as e:
    import logging
    logging.getLogger("ariv.core.config").warning("pydantic_settings not available (%s); using dummy BaseSettings.", e)
    class BaseSettings:
        def __init__(self, **data):
            for key, value in data.items():
                setattr(self, key, value)
        def dict(self):
            return self.__dict__
    class SettingsConfigDict(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)


def normalize_database_url(url: str) -> str:
    """Convert a raw provider DATABASE_URL into an asyncpg-compatible URL.

    Render managed Postgres (and many PAAS providers) expose a plain
    ``postgres://`` / ``postgresql://`` URL. SQLAlchemy async engines and
    asyncpg require the ``postgresql+asyncpg://`` driver prefix. The local
    default already carries the driver, so this is a no-op outside of
    production-style URLs.
    """
    if not url:
        return url
    if url.startswith("postgres://") or url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.split("://", 1)[1]
    return url

class Settings(BaseSettings):
    PROJECT_NAME: str = "ARIV"
    
    # Infrastructure
    DATABASE_URL: str = "postgresql+asyncpg://ariv_user:ariv_pass@localhost:5432/ariv_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    QDRANT_URL: str = "http://localhost:6333"
    # API key for managed/cloud Qdrant clusters (optional; empty for unauthenticated local Qdrant).
    QDRANT_API_KEY: str = ""
    # Canonical non-authoritative recovery-memory collection.  Decisioning and
    # measurement indexing must use the same collection contract.
    QDRANT_COLLECTION_NAME: str = "historical_cases"
    QDRANT_DISTANCE_METRIC: str = "Cosine"
    EMBEDDING_PROVIDER: str = "deterministic"
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-base-en-v1.5"
    EMBEDDING_DIMENSION: int = 768

    # Durable KnowledgeOutbox drainer (background reconciliation of Postgres ->
    # Qdrant memory). Seconds between claim/process sweeps. When a dedicated
    # Render worker service is running, set KNOWLEDGE_DRAIN_ENABLED=false on the
    # web service to avoid redundant sweepers competing with the worker.
    KNOWLEDGE_DRAIN_INTERVAL_SECONDS: float = 30.0
    KNOWLEDGE_DRAIN_ENABLED: bool = True

    @property
    def async_database_url(self) -> str:
        """DATABASE_URL normalized to the asyncpg driver prefix."""
        return normalize_database_url(self.DATABASE_URL)

    
    # Security & Provider Credentials
    INTERNAL_API_KEY: str = "test_internal_key"

    RAZORPAY_WEBHOOK_SECRET: str = "test_secret"
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_BASE_URL: str = "https://api.razorpay.com/v1"
    RAZORPAY_ENVIRONMENT: str = "SANDBOX"
    RAZORPAY_TIMEOUT_SECONDS: float = 10.0

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    TELEGRAM_TIMEOUT_SECONDS: float = 5.0

    DEMO_MODE: bool = True
    # Local/development demo account bound to a tenant at startup (DEMO_MODE only).
    # This is the operator/tenant mapping seed; it never enables unauthenticated access.
    DEMO_ACCOUNT_ID: str = "acc_demo_123"

    # Economic optimizer constants
    ECONOMIC_OPERATIONAL_COST: float = 10.0
    ECONOMIC_RISK_PENALTY: float = 5.0
    ECONOMIC_DETERMINISTIC_PRIOR: float = 0.6

    # LLM Provider Configuration
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT_SECONDS: float = 10.0

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

settings = Settings()
