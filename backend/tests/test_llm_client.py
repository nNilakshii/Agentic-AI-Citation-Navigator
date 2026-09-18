"""The LLM wrapper's retry and error classification (task 1.6).

These exist because free-tier Gemini rate-limits at 5 requests/minute, which a
single long paper can trip on its own. Getting the retry wrong is not a
performance problem — a swallowed 429 silently truncates a reading path.
"""

import asyncio

import pytest

from app.llm.client import (
    MAX_BACKOFF_SECONDS,
    GeminiClient,
    LLMError,
    LLMNotConfigured,
    _is_retryable,
    _retry_delay_seconds,
)


class FakeAPIError(Exception):
    """Stands in for google.genai.errors.APIError, which only needs a code."""

    def __init__(self, code, message=""):
        super().__init__(message or f"{code} error")
        self.code = code


# --- which failures are worth retrying ---------------------------------


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_transient_codes_are_retryable(code):
    assert _is_retryable(FakeAPIError(code))


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_permanent_codes_are_not_retryable(code):
    # A withdrawn model (404) or a bad key (401) fails identically next time;
    # retrying only delays the error the developer needs to see.
    assert not _is_retryable(FakeAPIError(code))


def test_a_non_api_error_is_not_retryable():
    assert not _is_retryable(ValueError("something else"))


# --- how long to wait --------------------------------------------------


def test_the_servers_own_retry_delay_is_honoured():
    # Gemini's 429 says how long its per-minute quota needs. Guessing shorter
    # just burns the next attempt.
    exc = FakeAPIError(429, "{'retryDelay': '46.2s'}")

    delay = _retry_delay_seconds(exc, attempt=0)

    assert 46.2 < delay <= 48.0


def test_backoff_grows_when_the_server_says_nothing():
    first = _retry_delay_seconds(FakeAPIError(503), attempt=0)
    later = _retry_delay_seconds(FakeAPIError(503), attempt=3)

    assert later > first


def test_backoff_is_capped():
    assert _retry_delay_seconds(FakeAPIError(503), attempt=20) <= MAX_BACKOFF_SECONDS
    huge = FakeAPIError(429, "{'retryDelay': '9999s'}")
    assert _retry_delay_seconds(huge, attempt=0) <= MAX_BACKOFF_SECONDS


def test_backoff_is_jittered():
    # Batches rate-limited together must not retry in lockstep and re-trip the
    # same limit.
    delays = {_retry_delay_seconds(FakeAPIError(503), attempt=2) for _ in range(20)}
    assert len(delays) > 1


# --- configuration -----------------------------------------------------


@pytest.fixture
def no_key(monkeypatch):
    """Hide whatever is in the developer's .env.

    ``GeminiClient(api_key=None)`` falls back to the configured key, so without
    this the test would make a real API call on a machine that has one — and
    quietly pass for the wrong reason on a machine that does not.
    """
    from app.config import Settings

    monkeypatch.setattr(
        "app.llm.client.get_settings", lambda: Settings(gemini_api_key=None)
    )


def test_constructing_without_a_key_does_not_raise(no_key):
    # It is a FastAPI dependency: raising here becomes an opaque 500 before any
    # handler can map it to a useful status.
    GeminiClient()


def test_calling_without_a_key_raises_the_configuration_error(no_key):
    client = GeminiClient()

    with pytest.raises(LLMNotConfigured) as caught:
        asyncio.run(client.generate_json(prompt="hi", schema={"type": "object"}))

    assert "GEMINI_API_KEY" in str(caught.value)


def test_a_placeholder_key_counts_as_unconfigured():
    client = GeminiClient(api_key="your-key-here")

    with pytest.raises(LLMNotConfigured):
        asyncio.run(client.generate_json(prompt="hi", schema={"type": "object"}))


def test_the_configuration_error_is_an_llm_error():
    # The endpoint catches LLMNotConfigured before LLMError; this ordering is
    # what makes a missing key a 503 rather than a 502.
    assert issubclass(LLMNotConfigured, LLMError)


def test_the_model_name_is_reported():
    assert GeminiClient(api_key="k", model="gemini-test").model == "gemini-test"
