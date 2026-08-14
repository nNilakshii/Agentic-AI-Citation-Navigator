from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Loaded from environment / .env. See ../../.env.example for the full key list."""

    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    openalex_email: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
