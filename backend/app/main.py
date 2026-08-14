from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

app = FastAPI(title="AURA Citation Navigator API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --- Phase 1: base reading assistant + goal-adaptive reading ---
# from app.api import reader
# app.include_router(reader.router, prefix="/api/reader", tags=["reader"])

# --- Phase 2: Citation Bridge (cited-span localization) ---
# from app.api import citation_bridge
# app.include_router(citation_bridge.router, prefix="/api/bridge", tags=["bridge"])

# --- Phase 3: Agentic Citation Chat ---
# from app.api import chat
# app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
