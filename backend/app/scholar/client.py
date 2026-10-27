"""Semantic Scholar, behind one rate limiter and a disk cache (task 2.2).

The API key allows **1 request per second, cumulative across all endpoints**
(``docs/architecture.md``). Two consequences shape this module:

- **One limiter for the whole process.** A limiter per call site would still
  exceed the quota whenever two code paths ran at once, so every request goes
  through the single :class:`_RateLimiter` below.
- **Every response is cached to disk**, keyed by the exact request. Re-running
  resolution or an evaluation then costs nothing; only genuinely new papers
  reach the network.

A failed request is never cached, for the reason learned in 1.6: a cached
failure becomes a permanent one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)

API = "https://api.semanticscholar.org/graph/v1"
CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache" / "s2"

#: Seconds between requests. The key allows one per second; a little over that
#: keeps clock jitter from producing a 429.
MIN_INTERVAL = 1.1
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 6

#: What resolution asks for on every cited paper.
PAPER_FIELDS = "title,year,authors,externalIds,openAccessPdf,venue"


class ScholarError(RuntimeError):
    """Semantic Scholar could not be reached or refused the request."""


class _RateLimiter:
    """At most one request per ``interval`` seconds, across all threads."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            delay = self._last + self.interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


_LIMITER = _RateLimiter(MIN_INTERVAL)


class SemanticScholar:
    """The few Graph API calls resolution needs."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        cache_dir: Path | None = CACHE_DIR,
        session: requests.Session | None = None,
    ) -> None:
        self._key = (
            api_key if api_key is not None else get_settings().semantic_scholar_api_key
        )
        self._cache = cache_dir
        self._session = session or requests.Session()
        self.network_calls = 0  # for tests and the QA report

    # --- calls ----------------------------------------------------------------

    def references(self, paper_ref: str) -> list[dict]:
        """Everything a paper cites, as Semantic Scholar has it.

        ``paper_ref`` is any id the API accepts: ``arXiv:1706.03762``,
        ``DOI:...``, or a paper id. One request returns up to 1,000 entries,
        each with the cited paper plus the citing sentences and their intents.
        """
        fields = f"contexts,intents,{PAPER_FIELDS}"
        body = self._get(
            f"/paper/{paper_ref}/references", {"fields": fields, "limit": 1000}
        )
        return body.get("data") or [] if body else []

    def batch(self, ids: list[str]) -> list[dict | None]:
        """Look up many papers in one request; ``None`` where one is unknown."""
        if not ids:
            return []
        out: list[dict | None] = []
        for start in range(0, len(ids), 500):  # the API's per-request ceiling
            chunk = ids[start : start + 500]
            body = self._post("/paper/batch", {"fields": PAPER_FIELDS}, {"ids": chunk})
            out.extend(body if isinstance(body, list) else [None] * len(chunk))
        return out

    def match_title(self, title: str) -> dict | None:
        """The single best title match, or ``None``. One request per call."""
        body = self._get(
            "/paper/search/match", {"query": title, "fields": PAPER_FIELDS}
        )
        data = (body or {}).get("data") or []
        return data[0] if data else None

    # --- transport ------------------------------------------------------------

    def _get(self, path: str, params: dict) -> Any:
        return self._request("GET", path, params, None)

    def _post(self, path: str, params: dict, payload: dict) -> Any:
        return self._request("POST", path, params, payload)

    def _request(self, method: str, path: str, params: dict, payload: dict | None):
        key = self._cache_key(method, path, params, payload)
        cached = self._read_cache(key)
        if cached is not None:
            return cached["body"]

        headers = {"x-api-key": self._key} if self._key else {}
        for attempt in range(MAX_ATTEMPTS):
            _LIMITER.wait()
            self.network_calls += 1
            try:
                response = self._session.request(
                    method,
                    API + path,
                    params=params,
                    json=payload,
                    headers=headers,
                    timeout=TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                if attempt == MAX_ATTEMPTS - 1:
                    raise ScholarError(f"{method} {path}: {exc}") from exc
                time.sleep(2**attempt)
                continue

            if response.status_code == 404:
                # "No such paper" and "no title match" are answers, not
                # failures: cache them so the same miss is not re-asked.
                self._write_cache(key, None)
                return None
            if response.status_code in (429, 500, 502, 503, 504):
                if attempt == MAX_ATTEMPTS - 1:
                    raise ScholarError(f"{method} {path}: HTTP {response.status_code}")
                # Semantic Scholar's 429 carries no Retry-After, and waits of
                # 1-4s exhausted every attempt even with requests 1.1s apart;
                # its window is evidently longer than one second. Back off
                # from 5s.
                wait = float(response.headers.get("Retry-After") or 5 * 2**attempt)
                logger.warning(
                    "Semantic Scholar %s; retrying in %.1fs", response.status_code, wait
                )
                time.sleep(min(wait, 60))
                continue
            if response.status_code >= 400:
                raise ScholarError(
                    f"{method} {path}: HTTP {response.status_code} {response.text[:200]}"
                )

            body = response.json()
            self._write_cache(key, body)
            return body
        raise ScholarError(f"{method} {path}: gave up after {MAX_ATTEMPTS} attempts")

    # --- cache ----------------------------------------------------------------

    @staticmethod
    def _cache_key(method, path, params, payload) -> str:
        raw = json.dumps([method, path, params, payload], sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _read_cache(self, key: str) -> dict | None:
        if self._cache is None:
            return None
        path = self._cache / f"{key}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write_cache(self, key: str, body: Any) -> None:
        if self._cache is None:
            return
        self._cache.mkdir(parents=True, exist_ok=True)
        path = self._cache / f"{key}.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps({"body": body}), encoding="utf-8")
        temp.replace(path)


@lru_cache
def get_scholar() -> SemanticScholar:
    """Injectable factory — FastAPI overrides this in tests."""
    return SemanticScholar()
