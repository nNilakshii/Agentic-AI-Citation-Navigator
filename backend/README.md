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
| `POST` | `/api/reader/papers/{paper_id}/references/resolve` | Identify each cited paper via Semantic Scholar (2.2); `?title_search=true` is slow |
| `GET` | `/api/reader/papers/{paper_id}/references/resolved` | The cached resolution; never calls Semantic Scholar |
| `POST` | `/api/reader/papers/{paper_id}/citations/{anchor_id}/localize?k=5` | Rank the cited paper's passages for one citation (2.5; BM25 + MiniLM since 2.7, with a `clear_match` flag); fetches and embeds on first use; 503 where sentence-transformers is not installed |
| `POST` | `/api/reader/papers/{paper_id}/citations/{anchor_id}/ask` | `{"question": "..."}` → answer from the cited work only, as quoted claims checked verbatim (3.4); `insufficient` rather than a guess |
| `GET` | `/api/reader/papers/{paper_id}/passages` | Candidate passages for localization (2.4), with what was left out and why |
| `POST` | `/api/reader/papers/{paper_id}/references/{reference_id}/text` | The cited paper's text (2.3): its PDF, parsed and openable as `cited_paper_id`; else its abstract; else `unavailable`, with the reasons |
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

## Localizer spot check (Phase 2.5)

```bash
python scripts/qa_localize.py --per-paper 2   # needs qa_fetch.py first; no network
```

Prints real citing sentences and their top passages for a human to judge. Accuracy is
measured on CL-SciSumm (2.6/2.7), not here.

## Candidate-passage gate (Phase 2.4)

```bash
python scripts/qa_passages.py    # samples + papers fetched by qa_fetch.py
```

Flags papers that kept under 30% of their sentences, and any whose kept passages look like
a reference list. Prints the leak detector's recall on removed bibliography, so a blind
detector is visible.

## Cited-text fetch gate (Phase 2.3)

```bash
python scripts/qa_fetch.py              # first 5 references of each sample
python scripts/qa_fetch.py --limit 20 --papers attention-is-all-you-need
```

Reports full text / abstract / unavailable, and groups why each attempt failed. Set
`OPENALEX_API_KEY` (free) or some OpenAlex title searches will be throttled. Fetched
papers go to `data/fetch-qa/` (gitignored), never the committed cache. A cold run is paced
by arXiv (one request per 3s).

## Reference resolution gate (Phase 2.2)

```bash
python scripts/qa_resolution.py    # cached: ~1s; cold: bounded by Semantic Scholar's rate limit
```

Lists every inexact title match for a human to check, and every unresolved entry.

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
