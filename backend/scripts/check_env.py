"""Check that `.env` is present and that each configured API key actually works.

Task 0.3. Each check hits the cheapest endpoint that requires authentication, so
running this costs nothing:

- Gemini:           models.list()        (no tokens generated, so no quota used)
- Anthropic:        GET /v1/models       (no tokens generated, so no billing)
- OpenAI:           GET /v1/models       (same)
- Semantic Scholar: a 1-result paper search
- OpenAlex:         a 1-result works query (no key; the email joins the polite pool)

Listing models doubles as discovery: it reports which models your tier can
actually reach, instead of hardcoding a name that may not be available to you.

Usage (from the repo root, with the backend venv active):

    python backend/scripts/check_env.py            # check whatever is configured
    python backend/scripts/check_env.py --offline  # skip network calls

Exit code is 0 when every configured key validates and at least one LLM key works.
Missing optional keys are reported but don't fail the run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ENV_FILE, get_settings  # noqa: E402

REQUEST_TIMEOUT_SECONDS = 15
OPENALEX_URL = "https://api.openalex.org/works"
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

OK = "  ok  "
WARN = " warn "
FAIL = " fail "


def check_gemini(api_key: str) -> tuple[str, str]:
    """List models — authenticated, but generates no tokens and uses no quota.

    Also reports which generate-capable models this key can reach, so the model
    name used later in Phase 1.6 comes from what's actually available rather
    than a guess.
    """
    from google import genai
    from google.genai import errors

    # Hold the client in a local: models.list() returns a lazy pager, and a
    # temporary client would be closed by GC before the pages are fetched.
    client = genai.Client(api_key=api_key)
    try:
        models = list(client.models.list())
    except errors.ClientError as exc:
        # An invalid Gemini key comes back as 400, not 401/403 — cover all three
        # so the hint points at the fix rather than at the status code.
        if exc.code in (400, 401, 403):
            return (
                FAIL,
                f"key rejected ({exc.code}) — regenerate at aistudio.google.com/apikey",
            )
        if exc.code == 429:
            return (
                WARN,
                "key valid but rate-limited right now (free tier) — retry shortly",
            )
        return FAIL, f"API error {exc.code}: {exc.message}"
    except errors.APIError as exc:
        return FAIL, f"API error: {exc}"
    except Exception as exc:  # network/transport failures aren't typed by the SDK
        return FAIL, f"could not reach the Gemini API: {exc}"

    usable = sorted(
        m.name.removeprefix("models/")
        for m in models
        if "generateContent" in (m.supported_actions or [])
    )
    if not usable:
        return (
            WARN,
            f"key valid, but no generate-capable models listed ({len(models)} total)",
        )

    preview = ", ".join(usable[:3])
    return OK, f"key valid — {len(usable)} usable models (e.g. {preview})"


def check_anthropic(api_key: str) -> tuple[str, str]:
    """List models via the official SDK — authenticated but generates no tokens."""
    import anthropic

    try:
        models = anthropic.Anthropic(api_key=api_key).models.list(limit=1)
    except anthropic.AuthenticationError:
        return (
            FAIL,
            "key rejected (401) — check it at console.anthropic.com/settings/keys",
        )
    except anthropic.APIStatusError as exc:
        return FAIL, f"API error {exc.status_code}: {exc.message}"
    except anthropic.APIConnectionError:
        return FAIL, "could not reach api.anthropic.com — check your network"

    sample = models.data[0].id if models.data else "none listed"
    return OK, f"key valid (models available, e.g. {sample})"


def check_openai(api_key: str) -> tuple[str, str]:
    """List models via the official SDK — authenticated but generates no tokens."""
    import openai

    try:
        openai.OpenAI(api_key=api_key).models.list()
    except openai.AuthenticationError:
        return FAIL, "key rejected (401) — check it at platform.openai.com/api-keys"
    except openai.APIStatusError as exc:
        return FAIL, f"API error {exc.status_code}"
    except openai.APIConnectionError:
        return FAIL, "could not reach api.openai.com — check your network"

    return OK, "key valid"


def check_semantic_scholar(
    api_key: str | None, session: requests.Session
) -> tuple[str, str]:
    """Search for one paper. Works unauthenticated, so a missing key is only a warning."""
    headers = {"x-api-key": api_key} if api_key else {}
    try:
        response = session.get(
            SEMANTIC_SCHOLAR_URL,
            params={"query": "citation intent classification", "limit": 1},
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return FAIL, f"request failed: {exc}"

    if response.status_code in (401, 403):
        return FAIL, "key rejected — remove it to use the shared unauthenticated pool"
    if response.status_code == 429:
        return WARN, "rate-limited right now; a key would raise the limit to 1 req/sec"
    if not response.ok:
        return FAIL, f"HTTP {response.status_code}"

    tier = "authenticated (1 req/sec)" if api_key else "unauthenticated (shared pool)"
    return OK, f"reachable, {tier}"


def check_openalex(email: str | None, session: requests.Session) -> tuple[str, str]:
    """Query one work. No key exists for OpenAlex; the email just joins the polite pool."""
    params = {"per-page": 1}
    if email:
        params["mailto"] = email
    try:
        response = session.get(
            OPENALEX_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        return FAIL, f"request failed: {exc}"

    if not response.ok:
        return FAIL, f"HTTP {response.status_code}"
    if not email:
        return WARN, "reachable, but no OPENALEX_EMAIL set (slower common pool)"
    return OK, f"reachable, polite pool as {email}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--offline", action="store_true", help="skip all network calls")
    args = parser.parse_args()

    if not ENV_FILE.exists():
        print(f"No .env found at {ENV_FILE}", file=sys.stderr)
        print("Create one with:  cp .env.example .env   (then fill in your keys)")
        return 1

    settings = get_settings()
    configured = settings.configured()
    print(f"Reading {ENV_FILE}\n")

    for name, is_set in configured.items():
        state = "set" if is_set else "not set (still a placeholder)"
        print(f"  {name:<28} {state}")

    if args.offline:
        print("\n--offline: skipping live checks.")
        return 0

    session = requests.Session()
    results: dict[str, tuple[str, str]] = {}

    print("\nValidating against live APIs...\n")

    if configured["gemini_api_key"]:
        results["Gemini"] = check_gemini(settings.gemini_api_key)
    if configured["anthropic_api_key"]:
        results["Anthropic"] = check_anthropic(settings.anthropic_api_key)
    if configured["openai_api_key"]:
        results["OpenAI"] = check_openai(settings.openai_api_key)

    results["Semantic Scholar"] = check_semantic_scholar(
        (
            settings.semantic_scholar_api_key
            if configured["semantic_scholar_api_key"]
            else None
        ),
        session,
    )
    results["OpenAlex"] = check_openalex(
        settings.openalex_email if configured["openalex_email"] else None, session
    )

    for service, (status, detail) in results.items():
        print(f"  [{status}] {service:<18} {detail}")

    failed = [name for name, (status, _) in results.items() if status == FAIL]
    has_llm = any(
        results.get(provider, ("", ""))[0] == OK
        for provider in ("Gemini", "Anthropic", "OpenAI")
    )

    print()
    if failed:
        print(f"Failed: {', '.join(failed)}", file=sys.stderr)
    if not has_llm:
        print(
            "No working LLM key yet. Phase 1.6 (goal-conditioned ranking) is the first "
            "task that needs one — everything before it runs without.\n"
            "Free option: https://aistudio.google.com/apikey -> GEMINI_API_KEY in .env",
            file=sys.stderr,
        )
    if not failed and has_llm:
        print("All configured services check out.")

    return 1 if (failed or not has_llm) else 0


if __name__ == "__main__":
    raise SystemExit(main())
