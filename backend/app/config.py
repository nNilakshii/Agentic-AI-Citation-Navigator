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
    #: Discovered via scripts/check_env.py. Flash is the ranking workhorse:
    #: cheap, fast, and 1.6 is a selection task rather than a reasoning one.
    gemini_model: str = "gemini-3.6-flash"
    #: 0 disables Gemini's thinking tokens. See app/llm/client.py.
    llm_thinking_budget: int = 0
    #: Parallel LLM calls. Measured free-tier limit for gemini-3.6-flash is
    #: 5 requests/min, so overlapping more than a pair just rate-limits us.
    llm_max_concurrency: int = 2
    #: Attempts per call, including the first. Free-tier 429s ask for a ~45s
    #: wait, so two retries covers a quota window without hanging the request.
    llm_max_attempts: int = 3
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    openalex_email: str | None = None

    #: Comma-separated origins allowed to call the API. The deployed frontend
    #: lives on a different host from the backend, so it must be named here.
    allowed_origins: str = "http://localhost:5173"
    #: Live rankings allowed per client per hour. Only *uncached* rankings
    #: count, so browsing the pre-ranked samples is never limited. Guards the
    #: shared free-tier quota from a single visitor on a public deployment.
    rank_limit_per_hour: int = 6

    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

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
