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

    # Context collectors (Prometheus metrics, Loki logs) queried during triage.
    prometheus_url: str = "http://prometheus:9090"
    loki_url: str = "http://loki:3100"
    collector_timeout_seconds: float = 10.0
    # Window around the incident to collect: lookback before it opened, and after.
    collector_window_before_minutes: int = 15
    collector_window_after_minutes: int = 5
    collector_step_seconds: int = 15
    # Caps so one noisy service can't blow up a snapshot (truncated flag is set when hit).
    collector_max_metric_points: int = 500
    collector_max_log_lines: int = 200
    collector_max_log_bytes: int = 64_000

    # Claude triage (analysis step). Empty API key = triage disabled (calls fail, recorded).
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_timeout_seconds: float = 30.0
    anthropic_max_retries: int = 2  # retries after the first attempt, on rate-limit/5xx/timeout
    anthropic_max_tokens: int = 4096  # output budget; too low truncates the JSON mid-string
    # Hard cap on the context sent to Claude in one triage call (approximate tokens).
    triage_max_input_tokens: int = 8_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
