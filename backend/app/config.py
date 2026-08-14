from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute, so the .env is found no matter which directory the process starts in
# (uvicorn from backend/, pytest from the repo root, a script from anywhere).
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Loaded from environment / .env. See ../../.env.example for the full key list."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    openalex_email: str | None = None

    def configured(self) -> dict[str, bool]:
        """Which keys have a non-empty, non-placeholder value."""
        return {
            name: bool(value) and "your-" not in value and "optional-" not in value
            for name, value in (
                ("gemini_api_key", self.gemini_api_key),
                ("anthropic_api_key", self.anthropic_api_key),
                ("openai_api_key", self.openai_api_key),
                ("semantic_scholar_api_key", self.semantic_scholar_api_key),
                ("openalex_email", self.openalex_email),
            )
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
