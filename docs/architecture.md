# Architecture

Decisions and their rationale, recorded as they're made. See `docs/TASKS.md` for the
build order and status.

---

## The load-bearing decision: one document model, addressed by character offset

Almost every feature in this project is "highlight this specific piece of a paper":

| Phase | Feature | What it needs |
|---|---|---|
| 1.7 | Goal-relevant reading path | Highlight a set of passages |
| 1.8 | Plain-language explanations | Quote the passage being explained |
| 2.12 | Cited-span localization | Highlight the exact referenced span |
| 3.4 | Grounded chat answers | Cite the span an answer came from |

These are the same operation against different span-selection logic. So the architecture
centers on a **single canonical parsed representation** in which every piece of text has a
stable address:

```
(paper_id, start_char, end_char)
```

Everything downstream — rankers, localizers, the chat agent — consumes and returns spans in
that form. The UI has exactly one job: given a span, highlight it. New features become new
ways of *choosing* spans, not new rendering paths.

**The consequence to respect:** offsets must be stable. If the parser changes and offsets
shift, every cached ranking, eval result, and stored annotation silently misaligns. So
`ParsedPaper` carries a `parser_version`, and the cache is keyed on it — changing the parser
invalidates derived data instead of corrupting it.

### `ParsedPaper` schema (Phase 1.1 output)

```jsonc
{
  "paper_id": "sha256 of the PDF bytes",
  "parser_version": "1",
  "source": { "filename": "...", "arxiv_id": "1706.03762", "title": "..." },
  "full_text": "the entire document as one string — offsets index into this",
  "sections": [
    { "title": "Introduction", "level": 1, "start_char": 0, "end_char": 4210 }
  ],
  "sentences": [
    {
      "id": "s0042",
      "start_char": 1200,
      "end_char": 1310,
      "section_id": 1,
      "page": 3,
      "bboxes": [ { "page": 3, "x0": 72.0, "y0": 340.1, "x1": 523.4, "y1": 352.7 } ]
    }
  ]
}
```

Two coordinate systems, deliberately. **Character offsets** are what the NLP works in —
embeddings, ranking, eval overlap metrics, LLM prompts. **Bounding boxes** are what the
renderer needs to draw a highlight over the PDF. Sentences carry both, so the mapping is a
lookup rather than a re-computation. A sentence gets multiple bboxes because it can wrap
across lines or columns.

Sentence is the unit because CL-SciSumm's gold annotations are sentence-level, so the eval
harness and the runtime representation agree without a conversion step.

### Building the offset ↔ bbox mapping (verified constraint for 1.1)

PyMuPDF exposes both views, but they do **not** agree character-for-character. Measured on
`data/samples/attention-is-all-you-need.pdf`, page 3:

| Source | Length |
|---|---|
| `page.get_text()` | 1827 chars |
| Concatenated `dict` spans | 1800 chars |

`get_text()` inserts line and block separators that the span stream doesn't contain. So the
tempting implementation — take `get_text()` as `full_text`, then `str.find()` each span to
get its offsets — drifts, and drifts *silently*: it produces plausible offsets that are
wrong by a growing amount down the page, misaligning every highlight.

**The rule for 1.1:** build `full_text` by walking the span stream and appending separators
explicitly, recording each span's `(start_char, end_char)` as it is appended. The offsets are
a byproduct of construction, never a lookup after the fact. `get_text()` is then useful only
as a sanity check, not as the source of truth.

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.14 + FastAPI | Same language as the ML stack; no serialization boundary between parsing, embeddings, and API |
| PDF parsing | **PyMuPDF** now, GROBID at Phase 2 | See below |
| Segmentation | Rule-based splitter, abbreviation-aware | Scientific text breaks naive splitters on "et al.", "Fig. 3", "0.05" |
| Embeddings | sentence-transformers (MiniLM → Specter2) | Runs locally, no API cost, no rate limit |
| LLM | Gemini free tier now; Claude at 2.8 | See "LLM provider" below |
| Scholarly data | Semantic Scholar (primary), OpenAlex (fallback) | S2 gives citation `contexts`/`intents`; OpenAlex needs no key |
| Frontend | React + Vite | Already scaffolded |
| PDF rendering | Allen AI `pdf-component-library` | Ships the highlight-overlay primitives Phase 1.7 needs — see "Decided" below |
| Storage | JSON files on disk, content-hash keyed | No database until something forces one |

### PDF parsing: PyMuPDF first, GROBID when Phase 2 needs it

PyMuPDF is already installed, pure Python, and gives text plus per-span bounding boxes —
which is exactly the two-coordinate-system requirement above. It does *not* give structured
bibliography parsing.

GROBID does, but it's a Java service behind Docker, and its value is concentrated in
reference-list extraction (Phase 2.1/2.2), not in Phase 1.

So: **PyMuPDF for Phase 1**, revisit at 2.1 where structured reference parsing is the actual
task. Deferring keeps the Phase 1 setup to `pip install` and avoids a Docker dependency
before it earns its place. The `ParsedPaper` schema is parser-agnostic, so swapping the
backend later means bumping `parser_version` and re-parsing, not reshaping the code.

### LLM provider: abstracted from the start

Phase 2.8 explicitly compares an embeddings localizer against an LLM localizer, and Phase 4
needs reproducible numbers. Both require swapping models without touching call sites, so LLM
access sits behind one narrow interface:

```python
class LLMClient(Protocol):
    def complete(self, prompt: str, *, system: str | None, max_tokens: int) -> str: ...
```

Gemini (free tier) is the development provider; Claude arrives at 2.8 via the direct API or
GCP Vertex, whichever is funded. Provider is a `.env` setting, not a code change.

**Model pinning:** development uses moving aliases (`gemini-flash-latest`); anything that
produces a number for the write-up pins an explicit version, since an alias shifting under a
recorded result would invalidate it.

### Semantic Scholar: 1 req/sec is a hard architectural constraint

The approved API key (2026-08-14) allows **1 request per second, cumulative across all
endpoints** — not per endpoint. Two consequences that shape `bridge/`:

**1. Batch, don't loop.** Resolving a bibliography one paper at a time is the obvious
implementation and the wrong one:

| Approach | ~2,000 references |
|---|---|
| `GET /paper/{id}` per reference | ~33 minutes |
| `POST /paper/batch`, 500 IDs per call | ~4 seconds |

Reference resolution must collect identifiers first and resolve them in batches. Per-paper
lookup is acceptable only for a single interactive click, never for an eval run.

**2. One shared rate limiter, not one per call site.** Because the quota is cumulative, a
per-endpoint or per-module limiter would still exceed it whenever two code paths run
concurrently. All Semantic Scholar traffic goes through a single client object owning one
limiter, with retry-and-backoff on 429.

Combined with the response cache below, a re-run of the eval harness should issue close to
zero live requests — only genuinely new papers reach the network.

### Caching: filesystem, content-addressed

Every expensive or rate-limited result is cached to disk under `data/cache/` (gitignored):
parsed PDFs keyed by `sha256(pdf_bytes) + parser_version`, Semantic Scholar and OpenAlex
responses keyed by request, embeddings keyed by `model + text hash`.

This is what makes the eval harness re-runnable without re-hitting rate-limited APIs, and
it's why the Semantic Scholar quota stays modest. Plain JSON files, no cache server — the
working set is a few hundred papers.

---

## Backend layout

```
backend/app/
  main.py          FastAPI app, router registration
  config.py        Settings from .env
  models/          Pydantic schemas — ParsedPaper, Span, Citation
  core/            PDF parsing, sentence segmentation, offset mapping
  ranking/         Phase 1.6 goal-conditioned passage ranking
  bridge/          Phase 2 citation anchors, reference resolution, localization
  llm/             Provider abstraction (Gemini / Claude)
  cache/           Content-addressed filesystem cache
  api/             Routers: reader, bridge, chat
scripts/           Operational scripts (fetch_sample_papers, check_env)
tests/
```

`core/` has no knowledge of FastAPI, and `eval/` imports it directly — the evaluation
harnesses run against library code, not over HTTP. That keeps eval runs fast and offline, and
means an eval result reflects the algorithm rather than the transport.

---

## Data flow

**Phase 1 — goal-adaptive reading**

```
PDF → parse (cached) → ParsedPaper → embed sentences (cached)
                                          ↓
                          goal + sentences → ranked spans
                                          ↓
                          UI: highlight spans via bboxes
```

**Phase 2 — citation bridge.** The key structural point: the cited paper goes through the
*same* parsing pipeline as the paper being read. There is no separate "cited paper" code
path.

```
citation anchor → bib entry → S2/OpenAlex → cited paper
                                                 ↓
                              fetch OA PDF → parse → ParsedPaper
                                                 ↓
            citance text + cited sentences → localizer → ranked spans
                                                 ↓
                              UI: side-by-side, jump + highlight
```

---

## Known risks

**Open-access coverage is the main threat to Phase 2.** Many cited papers have no
retrievable full text, and localization is impossible without it. The fallback ladder is:
open-access PDF → abstract only (localize within the abstract) → metadata only (report
"full text unavailable" rather than guessing). Coverage rate is worth *measuring and
reporting* — "localization accuracy on the N% of citations with retrievable full text" is an
honest result; silently evaluating only the easy subset is not.

**Offset drift** — mitigated by `parser_version` in the cache key, as above.

**Hallucination in Phase 3** — every factual claim must carry the span it came from, and the
agent must be able to say it doesn't know. Faithfulness is measured (3.8), not assumed.

**Scope creep** — the phases are ordered so each produces something demonstrable. Phase 2 is
the measurable research contribution; Phase 3 is an extension, not a prerequisite.

---

## Decided: PDF renderer

**Allen AI `pdf-component-library`** (the PaperCraft / Semantic Reader lineage), decided
2026-08-14.

The alternative was `react-pdf`: simpler, better documented, faster to a working reader. It
was rejected because the highlight overlay *is* the hard part of Phase 1, and react-pdf
leaves you to build it — absolute-positioned layers, PDF-point-to-CSS-pixel scaling, and
re-positioning on zoom and resize. `pdf-component-library` ships those primitives, so 1.7
becomes "pass the spans in" rather than "write an overlay engine."

It also shares a lineage with Semantic Reader and CiteRead, the prior work this project
builds on — building on the same foundation is easier to justify in the write-up than
reimplementing it.

Cost accepted: heavier install, thinner documentation, smaller community. If it proves
unworkable during 1.3, react-pdf is the fallback — and the `ParsedPaper` bboxes feed either
renderer, so the backend is unaffected by a switch.

## Open decisions

- **Sentence segmenter** — a hand-rolled abbreviation-aware splitter, or a dependency
  (pysbd / spaCy). Decide at 1.1; affects nothing outside `core/`.
- **GROBID adoption** — revisit at 2.1, where structured reference parsing is the task.
