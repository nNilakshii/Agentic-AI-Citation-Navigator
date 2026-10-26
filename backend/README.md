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

## Reading path — goal-conditioned ranking (Phase 1.6)

Ranks a paper's sentences for a reading goal (`skim` | `in-depth` | `critique`) and
returns the ones worth reading, each with a span, an importance and a one-line reason.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/reader/goals` | The goals and what each one surfaces |
| `GET` | `/api/reader/papers/{paper_id}/citations` | Every citation, linked to its reference entry (2.1) |
| `GET` | `/api/reader/coverage` | Which papers already have a path, per goal — what opens instantly |
| `POST` | `/api/reader/papers/{paper_id}/reading-path?goal=skim` | Rank (cached; `&force=true` to re-rank) |
| `GET` | `/api/reader/papers/{paper_id}/reading-path?goal=skim` | The cached path — never spends LLM quota |

```bash
curl -X POST "localhost:8000/api/reader/papers/$PAPER_ID/reading-path?goal=skim" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); \
      [print(f"[{i[\"importance\"]}] p{i[\"page\"]+1} {i[\"text\"][:80]}") for i in d["items"]]'
```

**The model selects, it never writes.** It sees numbered sentences and may answer only
with those numbers; each id is checked against the paper and dropped if unknown
(`n_hallucinated_ids` counts these), and every span and text is echoed from the parse. So
a reading path cannot contain a sentence the paper does not have.

Ranking costs LLM quota, so paths are cached per (paper, parser version, goal, ranker
version) — but **only when complete**. If a batch fails, `n_batches_failed` is non-zero
and the result is served without being cached, so a transient rate limit cannot leave a
permanently truncated path behind. Free-tier Gemini allows 20 requests a day
(and 5 a minute); see `docs/architecture.md`.

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

## Citation quality gate (Phase 2.1)

```bash
python scripts/qa_citations.py     # ~1s, no network
```

Fails if any paper links fewer than 85% of its citations, cites fewer than 90% of its
references, or links a citation to an entry that disagrees with it.

## Quality gate across the sample papers (Phase 1.10)

```bash
python scripts/qa_reading_paths.py --cached-only      # report only, no API calls
python scripts/qa_reading_paths.py --max-calls 15     # build a day's worth
python scripts/qa_reading_paths.py --papers bert.pdf  # one paper
python scripts/qa_reading_paths.py --force            # ignore cached paths
```

Exercises the real pipeline and fails on the things that make a reading path
untrustworthy rather than merely imperfect: a span that does not cut its own
text out of the document, an invented sentence id, a path that silently lost a
batch, an empty path, or three goals that select the same sentences (which
would mean the goal conditioning is inert).

The free tier allows 20 rankings a day, so a full 30-ranking sweep takes two
sittings: use `--max-calls 15` and run again tomorrow. Cached work is never
redone, so each run resumes where the last stopped.
