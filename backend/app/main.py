from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import reader
from app.api.limits import budget_remaining
from app.config import get_settings

app = FastAPI(title="AURA Citation Navigator API", version="0.1.0")

# The deployed frontend is on a different origin from the API, so the allowed
# list is configuration rather than a constant. See .env.example.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """Liveness, plus what is left of today's ranking budget.

    The budget is the thing most likely to make a deployment behave oddly, and
    it is invisible from the outside otherwise.
    """
    return {"status": "ok", "rankings_left_today": budget_remaining()}


# --- Phase 1: base reading assistant + goal-adaptive reading ---
app.include_router(reader.router, prefix="/api/reader", tags=["reader"])

# --- Phase 2: Citation Bridge (cited-span localization) ---
# from app.api import citation_bridge
# app.include_router(citation_bridge.router, prefix="/api/bridge", tags=["bridge"])

# --- Phase 3: Agentic Citation Chat ---
# from app.api import chat
# app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
