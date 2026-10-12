from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings shared by the API process.

    Database and provider fields are reserved configuration only in TASK-001. Their
    clients and runtime use are intentionally implemented by later tasks.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "ai-coach-intent-router"
    environment: str = "development"
    log_level: str = "INFO"
    request_id_header: str = "X-Request-ID"

    database_url: str = "mysql+asyncmy://user:password@localhost:3306/ai_coach"
    qwen_api_key: str | None = Field(default=None, repr=False)

    max_text_chars: int = 2000
    max_context_bytes: int = 16_384
    max_request_body_bytes: int = 1_048_576
    max_eval_file_bytes: int = 52_428_800
    max_eval_cases: int = 500
    provider_queue_wait_timeout: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
