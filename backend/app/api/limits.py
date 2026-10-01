"""A per-client budget for live rankings (deployment hardening).

One shared Gemini key serves every visitor, and the free tier allows 5 requests
a minute. Browsing the pre-ranked sample papers costs nothing — those paths
ship with the image — but an upload is a live call, so without a limit one
visitor can drain the quota for everyone and the demo goes quiet for a minute
at a time (which is exactly what it looks like when it is broken).

Deliberately an in-process fixed window: there is one backend process, the
limit protects a shared quota rather than enforcing a policy, and a Redis
dependency would cost more than the problem is worth. It resets on restart,
which on a scale-to-zero host is acceptable — the quota resets far faster.
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request

from app.config import get_settings

WINDOW_SECONDS = 3600

#: client key -> timestamps of live rankings inside the window.
_hits: dict[str, list[float]] = defaultdict(list)


def client_key(request: Request) -> str:
    """Identify the caller.

    Behind a proxy (every PaaS) the socket address is the proxy's, so the
    forwarded header is the only thing that distinguishes visitors. It is
    client-supplied and therefore spoofable — fine here, because this guards a
    quota rather than access to anything.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rank_budget(request: Request) -> None:
    """Raise 429 if this client has spent its hourly live-ranking budget.

    Call only on the path that actually reaches the LLM — a cache hit must
    never consume budget, or browsing the samples would exhaust it.
    """
    limit = get_settings().rank_limit_per_hour
    if limit <= 0:  # 0 disables the limit, for local development
        return

    key = client_key(request)
    now = time.time()
    recent = [t for t in _hits[key] if now - t < WINDOW_SECONDS]
    _hits[key] = recent

    if len(recent) >= limit:
        oldest = min(recent)
        retry_after = int(WINDOW_SECONDS - (now - oldest)) + 1
        raise HTTPException(
            status_code=429,
            detail=(
                f"You've ranked {limit} new papers this hour, which is the "
                "shared free-tier budget. The sample papers are pre-ranked and "
                "always available. Try again later."
            ),
            headers={"Retry-After": str(retry_after)},
        )
    _hits[key].append(now)


def reset_budgets() -> None:
    """Test helper — the window is process state."""
    _hits.clear()
