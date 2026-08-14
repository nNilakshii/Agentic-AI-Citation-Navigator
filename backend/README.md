# backend

FastAPI service: PDF parsing, goal-conditioned ranking, cited-span localization, agentic chat.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env   # fill in keys, once
uvicorn app.main:app --reload --port 8000
```

Health check: `GET http://localhost:8000/health`

## Test

```bash
pytest
```
