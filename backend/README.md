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
Interactive API docs: <http://localhost:8000/docs>

## Reader API (Phase 1.1 / 1.2)

Papers are addressed by `paper_id` — the sha256 of the PDF bytes — so uploading
the same paper twice is idempotent. Parses are cached under `data/cache/`, keyed
by `paper_id` *and* `parser_version`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/reader/papers` | Upload a PDF, get a `ParsedPaper` |
| `POST` | `/api/reader/papers/samples/{name}` | Parse a `data/samples` PDF — no upload needed |
| `GET` | `/api/reader/samples` | List the local sample PDFs |
| `GET` | `/api/reader/papers` | List cached parses (summaries) |
| `GET` | `/api/reader/papers/{paper_id}` | The full `ParsedPaper` |
| `GET` | `/api/reader/papers/{paper_id}/outline` | Sections only — for the reader sidebar |
| `GET` | `/api/reader/papers/{paper_id}/pdf` | The stored PDF bytes, for rendering |

Add `?force=true` to either `POST` to bypass the cache and re-parse.

```bash
# parse a sample paper and read off its outline
curl -X POST localhost:8000/api/reader/papers/samples/attention-is-all-you-need.pdf \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["paper_id"]); \
                [print(s["level"], s["title"]) for s in d["sections"]]'
```

## Test

```bash
pytest
```
