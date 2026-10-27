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
| PDF rendering | **`react-pdf` 10 (pdf.js 5)** | Overlay written in-house; the alternative shipped a known RCE — see "Decided" below |
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

### Gemini free tier: 20 requests a day shapes everything

Two limits, measured against `gemini-3.6-flash`:

| Limit | Value | Found |
|---|---|---|
| `GenerateRequestsPerMinutePerProjectPerModel` | **5 / minute** | 2026-09-05, building 1.6 |
| `GenerateRequestsPerDayPerProjectPerModel` | **20 / day** | 2026-10-01, during the 1.10 sweep |

A 429 carries a `retryDelay` of ~45s in both cases, which is why the per-minute limit was
the only one visible at first: a run small enough to finish never reached the daily cap.
The 1.10 sweep needed thirty rankings and hit the daily limit thirty-nine times.

**The daily cap is the binding constraint, and it is global** — one number for the whole
project, not a rate each caller gets. Three things follow.

**1. One paper should be one request.** A 15-page paper is ~300 rankable sentences. Early
1.6 used a 200-sentence batch, so every paper took two calls — and ranking all three goals
took six, over the limit. The first batch was rate-limited every time, which silently
dropped the *front half of the paper*: no abstract, no introduction, no method. The ranking
looked plausible because every sentence in it was real. Batch size is now 400, so a typical
paper is a single call.

**2. A partial result must never be cached.** This is the subtler half. Batches fail
independently, and a path missing one batch is indistinguishable from a complete one by
inspection — the sentences it contains are genuine, there are just fewer of them. Caching
it would turn a transient 429 into a permanently truncated reading path for that paper and
goal. `ReadingPath.n_batches_failed` records this and the endpoint caches only when it is
zero, so a rate-limited run costs latency rather than correctness.

**3. A deployment needs a budget, not a rate limit.** A per-visitor rate limit does not
protect a global daily quota: a handful of visitors well inside their own allowance can
still spend the day's twenty between them. So the API carries a global daily budget
(`RANK_BUDGET_PER_DAY`) *and* a per-visitor share (`RANK_LIMIT_PER_VISITOR`), and reports
what is left on `/health`. A public demo therefore ships every sample paper pre-ranked —
browsing costs nothing, and only uploads draw on the budget.

Retries honour the server's own `retryDelay` rather than guessing, with jitter so batches
limited together don't retry in lockstep and trip the same window again.

Note the model itself is not stable ground: `gemini-2.5-flash` still appears in
`models.list()` but returns 404 for new keys, pointing at `gemini-3.6-flash`. The model
name is a setting (`GEMINI_MODEL`), not a constant, and `scripts/check_env.py` reports what
a given key can actually reach.

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

## Decided: PDF renderer — ~~pdf-component-library~~ **react-pdf**

Originally decided 2026-08-14 in favour of Allen AI's `pdf-component-library` (the
PaperCraft / Semantic Reader lineage), because the highlight overlay is the hard part of
Phase 1 and that library ships the primitives for it. **Reversed at 1.3 on 2026-08-26**,
after trying the install the original entry said to try.

`@allenai/pdf-components@1.0.2` — last published 2022 — is not usable here:

| Finding | Consequence |
|---|---|
| Peer-depends on `react@^16.8.0` | Refuses to install against this project's React 18 without `--legacy-peer-deps` |
| Hard-pins `react-pdf@6.0.0-beta.2` → `pdfjs-dist@2.14.305` | Inherits **GHSA-wgrm-67xf-hhpq**: arbitrary JavaScript execution on opening a malicious PDF, fixed only in pdf.js ≥ 4.2 |
| Published `package.json` declares no `main`, `module` or `exports` | Bundler resolution fails out of the box |

The security finding is the decisive one, and it is specific to this project rather than
generic hygiene: **Phase 2.3 fetches cited-paper PDFs from the open web and renders them.**
Shipping a reader that executes script from a fetched PDF would make the citation bridge —
the measurable research contribution — the attack surface.

So: **`react-pdf@10` (pdf.js 5.x, patched)**, which the original entry pre-authorised as the
fallback. Production dependencies audit clean.

The accepted cost was writing the overlay ourselves. It came to about forty lines
(`src/lib/geometry.js` + `src/components/HighlightLayer.jsx`), because the backend already
emits exact bboxes in PDF points with a top-left origin — the same orientation as CSS — so
the transform is one multiply by a scale factor. That scale is *measured* from the rendered
page (`renderedWidth / originalWidth`) rather than assumed, which is what keeps highlights
aligned through zoom and resize.

Verified in Chrome against the Transformer paper: 56/56 highlight rectangles land inside the
correct page, all line-height sized, none zero-size, and still 56/56 aligned after resizing
the window from 1440px to 1000px.

Losing the Semantic Reader lineage is a real cost to the write-up's "builds on prior work"
framing. It is recoverable: the citation is to the *ideas* in Semantic Reader and CiteRead,
which the literature review already covers, and `ParsedPaper` bboxes feed either renderer, so
a future switch remains a frontend-only change.

## Decided: sentence segmenter — hand-rolled

Settled at 1.1 (2026-08-26). `app/core/segmentation.py`, no new dependency.

pysbd and spaCy both segment better prose than a hand-rolled splitter, and both were
rejected for the same reason: the requirement here is not *sentence texts* but *offsets into
the exact string we built*. A library that normalises whitespace or re-tokenises breaks the
offset contract the whole architecture rests on. Scientific text also needs a custom
abbreviation list either way ("et al.", "Fig. 3", "0.05", "J. Doe").

The splitter also enforces a 1000-character cap, splitting at whitespace. Measured on the
sample papers this fires on 3 of 6,421 spans (0.05%), all extracted table bodies with no
terminal punctuation anywhere. Splitting them does not make them prose — it bounds what the
embedder (1.6) and the LLM prompts have to accept.

## What 1.1 actually needed, beyond the plan

Verified against all ten sample papers: **0 offset mismatches, 0 sentences without
geometry**, 0.3–1.0 s per paper. Four corrections the plan did not anticipate, each one
found by parsing real PDFs rather than synthetic ones:

| Symptom | Cause | Fix |
|---|---|---|
| `3` and `Model Architecture` became two sections | LaTeX emits the section number as its own block | Bare numbers are merged with the following line |
| Half of a two-column heading became a section | ACM templates wrap long headings | A heading absorbs an adjacent continuation line set in the same type |
| The title came out as `arXiv:1706.03762v7 [cs.CL]` | The rotated arXiv stamp is the largest type on page 1 | Excluded from both heading and title detection |
| Table rows (`84.2 91.1`, `93.1`) became sections | They match "numbered heading" on typography alone | Titles must start with a letter; section numbers must be monotonic (`_NumberingGuard`) |

The last one is the general lesson: **typography alone cannot separate a section number from
a table cell** — both are bold, both are short, both begin with a number. Document-level
sequence is the signal that does, so numbering is validated against what came before.

Heading detection stays a heuristic, and one-off run-in labels still slip through. That is
tolerable by construction: a missed heading only means text belongs to the previous section,
and GROBID is already queued for 2.1 where reference parsing forces the issue.

## What 1.3 / 1.4 needed, beyond the plan

Two defects that only a real browser could show, both in the same place — the outline's
"you are here" marker fighting the reader's explicit choice:

1. A smooth scroll travels *through* the pages between here and the target, and the
   `IntersectionObserver` reports every one of them. Clicking "3.2.1" left the outline
   marking "3 Model Architecture", whichever section the jump happened to fly past.
2. On arrival, the target page's *first* section is not necessarily the one clicked — a page
   holds several sections, so page-level tracking is strictly coarser than a click.

Both are fixed in `App.jsx`: scroll reports are ignored for 1200 ms after a jump, and an
explicit selection wins on its own page. The general lesson for the phases ahead —
2.12 jumps to a cited span, 1.7 jumps along a reading path — is that **scroll position is a
lagging, lower-resolution signal than an intentional navigation**, and must never overwrite
one.

## Decided: citations are a separate artifact, and GROBID can wait

Settled at 2.1 (2026-10-26).

**Separate from the parse.** Putting citations into `ParsedPaper` would bump
`parser_version`, and every cached reading path is keyed on it — so the change would
silently invalidate rankings that cost quota to build, including those the live demo
serves. The citation map is derived from a parse on request instead (a few ms per paper)
and carries its own `citation_version`.

**No GROBID yet.** The plan was to revisit GROBID here, for structured reference parsing.
Hand-rolled detection reached 99.1% of citations linked and 99.4% of references cited
across the ten samples, with every remaining miss absent from the source text. GROBID
would add a Java service and a Docker dependency for at most those last few. Revisit if
cited-paper resolution in 2.2 turns up entries the parser has mangled.

**How it is measured without labels.** Link rate alone was misleading: two papers scored
100% while finding a single reference. Reference *coverage* — every reference should be
cited at least once — is what exposed missed citations, and a per-link consistency check
(number = label, or surname + year match) catches wrong links. `scripts/qa_citations.py`.

## Decided: resolve references through the citing paper, not one by one

Settled at 2.2 (2026-10-26).

Semantic Scholar's `/paper/{id}/references` returns every work a paper cites in **one
request** — titles, ids, open-access links, even the citing sentences and their intents.
Matching our parsed entries to that list by title resolves 96.5% of the samples' 513
references in ~10 requests. Searching per entry would have taken 513 requests, and in
practice far longer than 513 seconds (below).

**The rate limit is tighter than advertised.** The key is documented at one request per
second, but requests spaced 1.1s apart still drew 429s, and recovery needed waits of up to
80 seconds. Two consequences: per-entry title search is opt-in and capped, never part of
an interactive request; and the CL-SciSumm harness in 2.6 must lean entirely on the cache.

**Matching is by title** because a reference always contains the cited title, while author
and venue formatting vary by style. Hyphens and apostrophes are deleted before comparing
(PDFs join "Semi-\nsupervised"; Semantic Scholar keeps the hyphen), and a near-match that
is missing an ordinal or number is rejected — series papers differ by exactly that word.

**PDFs prefer arXiv.** Semantic Scholar lists an open-access PDF for far fewer papers than
have an arXiv id, and every arXiv paper is free to read; 72% of references have a
fetchable PDF this way. The rest are 2.3's abstract fallback.

## Open decisions

- **GROBID adoption** — revisit at 2.1, where structured reference parsing is the task.
- **Browser-level test harness** — 1.3/1.4 were verified with a throwaway Playwright script
  driving system Chrome (18 assertions: rasterisation, outline, highlight geometry, resize
  alignment, upload, console errors). It caught two bugs that 64 jsdom tests could not, since
  jsdom has no canvas and no layout. Worth adopting as a committed suite; deferred because it
  adds a heavy dependency, and Phase 4.5 (reproducibility) is the natural place to decide.
