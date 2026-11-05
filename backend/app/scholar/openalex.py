"""OpenAlex, for the abstracts Semantic Scholar may not show (task 2.3).

Semantic Scholar withholds abstracts for many publishers ("fields elided by
the publisher"), which left the abstract fallback rescuing 2 of 80 sample
references. OpenAlex is free, needs no key, and carries abstracts for many of
the same papers, stored as an inverted index (word -> positions) that
:func:`abstract_text` turns back into prose.

Same contract as the Semantic Scholar client: responses are cached to disk,
"not found" is an answer and is cached, a failure is never cached.

Access changed in 2026: keyless search is throttled whenever OpenAlex is under
load (a 429 with Retry-After, ~30s), and keyless callers share one daily
budget per IP; the ``mailto`` email no longer raises any limit. A free key in
``OPENALEX_API_KEY`` avoids both. Key and email are sent only to OpenAlex and
kept out of the cache key.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

from app.config import get_settings

API = "https://api.openalex.org"
CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache" / "openalex"
#: OpenAlex allows 10 requests a second; a fifth of that is plenty here.
MIN_INTERVAL = 0.5
TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 3
#: Longest Retry-After honoured; keyless search asks for ~30s under load.
MAX_RETRY_WAIT = 45.0
FIELDS = "id,title,doi,abstract_inverted_index,best_oa_location"


class OpenAlexError(RuntimeError):
    """OpenAlex could not be reached or refused the request."""


class OpenAlex:
    """Look up one work by DOI or by title. Injectable, so tests stay offline."""

    def __init__(
        self,
        email: str | None = None,
        api_key: str | None = None,
        cache_dir: Path | None = CACHE_DIR,
        session: requests.Session | None = None,
    ) -> None:
        settings = get_settings()
        self._email = email if email is not None else settings.openalex_email
        self._key = api_key if api_key is not None else settings.openalex_api_key
        self._cache = cache_dir
        self._session = session or requests.Session()
        self._lock = threading.Lock()
        self._last = 0.0
        self.network_calls = 0

    def by_doi(self, doi: str) -> dict | None:
        return self._get(f"/works/doi:{doi}", {"select": FIELDS})

    def by_title(self, title: str) -> dict | None:
        """The top title-search hit, unverified — the caller checks the match."""
        # Colons and commas are syntax in OpenAlex filters; a title holding
        # one ("TVM: An Automated ...") silently found nothing.
        query = re.sub(r"[^\w\s]", " ", title).strip()
        if not query:
            return None
        body = self._get(
            "/works",
            {"filter": f"title.search:{query}", "per-page": 1, "select": FIELDS},
        )
        results = (body or {}).get("results") or []
        return results[0] if results else None

    # --- transport ------------------------------------------------------------

    def _get(self, path: str, params: dict) -> Any:
        key = hashlib.sha256(
            json.dumps([path, params], sort_keys=True).encode()
        ).hexdigest()
        cached = self._read_cache(key)
        if cached is not None:
            return cached["body"]

        sent = dict(params)
        if self._email:
            sent["mailto"] = self._email
        if self._key:
            sent["api_key"] = self._key
        for attempt in range(MAX_ATTEMPTS):
            self._pace()
            self.network_calls += 1
            try:
                response = self._session.get(
                    API + path, params=sent, timeout=TIMEOUT_SECONDS
                )
            except requests.RequestException as exc:
                if attempt == MAX_ATTEMPTS - 1:
                    raise OpenAlexError(
                        f"GET {path}: {exc.__class__.__name__}"
                    ) from exc
                time.sleep(2**attempt)
                continue
            if response.status_code == 404:
                self._write_cache(key, None)
                return None
            if response.status_code in (429, 500, 502, 503, 504):
                if attempt == MAX_ATTEMPTS - 1:
                    raise OpenAlexError(f"GET {path}: HTTP {response.status_code}")
                retry_after = response.headers.get("Retry-After", "")
                wait = (
                    float(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1)
                )
                time.sleep(min(wait, MAX_RETRY_WAIT))
                continue
            if response.status_code >= 400:
                raise OpenAlexError(f"GET {path}: HTTP {response.status_code}")
            body = response.json()
            self._write_cache(key, body)
            return body
        raise OpenAlexError(f"GET {path}: gave up after {MAX_ATTEMPTS} attempts")

    def _pace(self) -> None:
        with self._lock:
            delay = self._last + MIN_INTERVAL - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()

    def _read_cache(self, key: str) -> dict | None:
        if self._cache is None:
            return None
        try:
            return json.loads((self._cache / f"{key}.json").read_text(encoding="utf-8"))
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


def abstract_text(work: dict | None) -> str | None:
    """Rebuild an abstract from OpenAlex's word -> positions index."""
    index = (work or {}).get("abstract_inverted_index") or {}
    placed = [(pos, word) for word, positions in index.items() for pos in positions]
    if not placed:
        return None
    return " ".join(word for _, word in sorted(placed))


@lru_cache
def get_openalex() -> OpenAlex:
    """Injectable factory — FastAPI overrides this in tests."""
    return OpenAlex()
