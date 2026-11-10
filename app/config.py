from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables (and .env if present)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "opspilot"
    environment: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://opspilot:opspilot@localhost:5432/opspilot"
    redis_url: str = "redis://localhost:6379/0"

    # Bearer token for the management API (/incidents, ...). Empty = API disabled (fail closed).
    api_token: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
