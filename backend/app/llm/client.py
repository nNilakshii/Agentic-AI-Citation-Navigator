"""A small JSON-in/JSON-out LLM wrapper (task 1.6, first use).

Deliberately narrow: everything this project asks of an LLM — goal-conditioned
ranking now, citation intent and grounded answers in Phase 3 — is "return
structured data conforming to this schema". So the only method is
:meth:`LLMClient.generate_json`, and the provider is free to enforce the schema
however it likes.

Gemini is the dev provider (task 0.3: free tier, no card). Anthropic/Vertex are
deferred to Phase 2.8, where model quality is the thing being measured — the
:class:`LLMClient` protocol is the seam they will slot into.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from typing import Any, Protocol

from app.config import get_settings

logger = logging.getLogger(__name__)

#: Status codes worth another go: rate limit, and the transient server-side
#: ones. Everything else (401, 404 for a withdrawn model, a bad schema) will
#: fail identically on a retry, so retrying only wastes the caller's time.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

#: Ceiling on a single backoff. Gemini's 429 for a per-minute quota asks for
#: ~45s; anything much beyond that is better surfaced than slept through.
MAX_BACKOFF_SECONDS = 60.0

_RETRY_DELAY = re.compile(r"'retryDelay':\s*'(\d+(?:\.\d+)?)s'")


class LLMError(RuntimeError):
    """The model could not be reached, or returned something unusable."""


class LLMNotConfigured(LLMError):
    """No API key. Distinct from a call failure: the fix is configuration."""


class LLMClient(Protocol):
    """What the rest of the codebase depends on. Easy to fake in tests."""

    model: str

    async def generate_json(
        self, *, prompt: str, schema: dict[str, Any], system: str | None = None
    ) -> Any:
        """Return parsed JSON conforming to ``schema``, or raise :class:`LLMError`."""
        ...


class GeminiClient:
    """:class:`LLMClient` over google-genai, using native structured output.

    Structured output matters here: it removes the "model wrapped its JSON in
    prose" failure mode entirely, so the caller's validation can be about
    *content* (are these real sentence ids?) rather than syntax.
    """

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.gemini_model
        self._api_key = api_key or settings.gemini_api_key
        self._client = None  # built lazily; see _get_client

    def _get_client(self):
        # Constructing must not raise: this is a FastAPI dependency, and an
        # exception during dependency resolution becomes an opaque 500 before
        # any handler can map it to a useful status. So the missing-key check
        # lives here, on the call path, where the endpoint can catch it.
        if not self._api_key or "your-" in self._api_key:
            raise LLMNotConfigured(
                "GEMINI_API_KEY is not set. Add it to .env — see .env.example, "
                "and run `python backend/scripts/check_env.py` to verify."
            )
        # Import inside, so importing this module (and therefore the API) does
        # not require the SDK to be installed until a call is actually made.
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def generate_json(
        self, *, prompt: str, schema: dict[str, Any], system: str | None = None
    ) -> Any:
        from google.genai import errors, types

        settings = get_settings()
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            # Ranking should be reproducible run to run: the same paper and
            # goal must not produce a different reading path each time.
            temperature=0.0,
            system_instruction=system,
            # This is a selection task, not a reasoning one. Thinking tokens
            # cost latency and free-tier quota without improving it.
            thinking_config=types.ThinkingConfig(
                thinking_budget=settings.llm_thinking_budget
            ),
        )
        # Resolved before the try: a missing key is a configuration fault and
        # must not be caught below and reported as an upstream failure.
        gemini = self._get_client()
        attempts = max(1, settings.llm_max_attempts)
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                response = await gemini.aio.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                break
            except errors.APIError as exc:
                last = exc
                if not _is_retryable(exc) or attempt == attempts - 1:
                    raise LLMError(f"{self.model} call failed: {exc}") from exc
                delay = _retry_delay_seconds(exc, attempt)
                logger.warning(
                    "%s: %s — retrying in %.1fs (attempt %d/%d)",
                    self.model,
                    getattr(exc, "code", "error"),
                    delay,
                    attempt + 2,
                    attempts,
                )
                await asyncio.sleep(delay)
            except Exception as exc:  # network, timeout, SDK-internal
                raise LLMError(f"{self.model} call failed: {exc}") from exc
        else:  # every attempt was retryable and every one failed
            raise LLMError(
                f"{self.model} call failed after {attempts} attempts: {last}"
            )

        text = (response.text or "").strip()
        if not text:
            # Usually a safety block or a hit token ceiling; both are actionable
            # only if we say which.
            reason = getattr(response, "prompt_feedback", None)
            raise LLMError(f"{self.model} returned no content (feedback: {reason})")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"{self.model} returned invalid JSON despite a response schema: "
                f"{text[:200]}"
            ) from exc


def _is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    return code in RETRYABLE_STATUS


def _retry_delay_seconds(exc: Exception, attempt: int) -> float:
    """How long to wait before the next attempt.

    Gemini's 429 states how long its per-minute quota needs (``retryDelay``),
    which beats guessing — on the free tier the guess is always far too short.
    Falls back to exponential backoff with jitter, the jitter being what stops
    several batches that were rate-limited together from retrying in lockstep
    and tripping the same limit again.
    """
    match = _RETRY_DELAY.search(str(exc))
    if match:
        # A second of slack: retrying at the exact boundary tends to 429 again.
        return min(float(match.group(1)) + 1.0, MAX_BACKOFF_SECONDS)
    return min(2.0**attempt + random.uniform(0, 1), MAX_BACKOFF_SECONDS)


def get_llm_client() -> LLMClient:
    """Injectable factory — FastAPI overrides this in tests."""
    return GeminiClient()
