"""Budgets for live rankings (deployment hardening).

Measured 2026-10-01: the Gemini free tier allows **20 `generateContent`
requests per day** per model, alongside the better-known 5-per-minute limit.
The daily cap is the binding one and it is *global* — one number shared by
every visitor to a deployment, not a rate each of them gets.

That makes a per-visitor rate limit insufficient on its own. Three visitors on
a generous per-visitor allowance would spend the whole day's quota before
lunch, and everyone after them meets a reader that silently fails to rank
anything. So there are two budgets:

- a **global daily** budget, which is what actually protects the quota, and
- a **per-visitor daily** cap, so one person cannot take all of it.

Browsing the pre-ranked sample papers costs nothing and is never limited:
these are checked only on the path that truly reaches the model.

Deliberately in-process. There is one backend process; the budget guards a
quota rather than enforcing a policy; and it resets on restart, which is
acceptable because the thing it protects resets daily anyway.
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request

from app.config import get_settings

DAY_SECONDS = 86400

#: Timestamps of live rankings, globally and per client, within the window.
_global: list[float] = []
_per_client: dict[str, list[float]] = defaultdict(list)


def client_key(request: Request) -> str:
    """Identify the caller.

    Behind a proxy (every PaaS) the socket address is the proxy's, so the
    forwarded header is the only thing that distinguishes visitors. It is
    client-supplied and therefore spoofable — acceptable, because the global
    budget is the real protection and this only stops honest over-use.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _recent(stamps: list[float], now: float) -> list[float]:
    return [t for t in stamps if now - t < DAY_SECONDS]


def check_rank_budget(request: Request) -> None:
    """Raise if this ranking would exceed either budget.

    Call only where an LLM call actually follows — a cache hit must never
    consume budget, or browsing the samples would exhaust the day.
    """
    settings = get_settings()
    global _global

    now = time.time()
    _global = _recent(_global, now)

    # 503, not 429: the deployment is out of capacity for the day, which is a
    # different thing from this visitor asking too often.
    if (
        settings.rank_budget_per_day > 0
        and len(_global) >= settings.rank_budget_per_day
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Today's ranking budget is spent — this demo runs on a free "
                "API tier that allows 20 new papers a day. Every sample paper "
                "is already ranked and works normally; uploads will work again "
                "tomorrow."
            ),
        )

    key = client_key(request)
    mine = _recent(_per_client[key], now)
    _per_client[key] = mine

    if (
        settings.rank_limit_per_visitor > 0
        and len(mine) >= settings.rank_limit_per_visitor
    ):
        raise HTTPException(
            status_code=429,
            detail=(
                f"You've ranked {settings.rank_limit_per_visitor} new papers "
                "today, which is this demo's per-visitor share of a free API "
                "tier. The sample papers are pre-ranked and always available."
            ),
            headers={"Retry-After": str(DAY_SECONDS)},
        )

    _global.append(now)
    _per_client[key].append(now)


def budget_remaining() -> int:
    """Live rankings left today, for the health endpoint."""
    settings = get_settings()
    if settings.rank_budget_per_day <= 0:
        return -1  # unlimited
    return max(0, settings.rank_budget_per_day - len(_recent(_global, time.time())))


def reset_budgets() -> None:
    """Test helper — the budgets are process state."""
    global _global
    _global = []
    _per_client.clear()
