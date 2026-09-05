from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "ARIV"
    
    # Infrastructure
    DATABASE_URL: str = "postgresql+asyncpg://ariv_user:ariv_pass@localhost:5432/ariv_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION_NAME: str = "recovery_measurements"
    QDRANT_DISTANCE_METRIC: str = "Cosine"
    EMBEDDING_PROVIDER: str = "deterministic"
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-base-en-v1.5"
    EMBEDDING_DIMENSION: int = 768

    
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

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

settings = Settings()
