# AURA Citation Navigator — Task Tracker

Repo-native progress tracker. Kept in sync with git commits (see "How to update" below).
Mirror the high-level status into the Google Sheet whenever you want a shareable view.

**Status key:** `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked
Annotate each task with a short status/date, e.g. `— Done 2026-08-14` or `— Blocked: GROBID setup`.

## How to update (after a work session)
Review the git commits since the last update, then check off completed tasks, mark
in-progress ones `[~]`, and add the date. Leave a one-line note on anything blocked.
Task text and IDs stay as they are.

---

## Phase 0 · Setup & Foundations
- [x] **0.1** Create GitHub repo + project skeleton — Done 2026-08-14
- [x] **0.2** Set up local dev environment (Python venv + Node) — Done 2026-08-14: backend/.venv (Py 3.14.6, all requirements installed, pytest passes), frontend node_modules (Node 25.2.1, vite build passes)
- [x] **0.3** Get API keys & configure `.env` (LLM, Semantic Scholar, OpenAlex) — Done 2026-08-14: `.env` configured, all checks green via `backend/scripts/check_env.py`. LLM provider = **Gemini free tier** (key verified, 28 gemini-* models available); OpenAlex on the polite pool. Anthropic/Vertex deferred to Phase 2.8 where model quality is what's measured. Semantic Scholar key approved + configured (1 req/sec cumulative across all endpoints — see `docs/architecture.md`, this forces batch resolution + a shared rate limiter in Phase 2.2)
- [x] **0.4** Literature review — reading tools (Semantic Reader, CiteRead, PaperMage) — Done 2026-08-14: `docs/literature-review.md` Part A (Semantic Reader, PaperMage, GROBID, CiteRead, CiteSee, CitePeek)
- [x] **0.5** Literature review — citation NLP (CL-SciSumm, SciCite, Specter2) — Done 2026-08-14: `docs/literature-review.md` Part B + Part C synthesis (revised novelty claim)
- [x] **0.6** Finalize architecture & stack (`docs/architecture.md`) — Done 2026-08-14: document model (char offsets + bboxes), stack table, backend layout, data flow, risks. Decided PyMuPDF-then-GROBID and Allen AI pdf-component-library
- [x] **0.7** Collect 5–10 sample arXiv papers for testing — Done 2026-08-14: `backend/scripts/fetch_sample_papers.py` fetches 10 curated open-access arXiv PDFs into `data/samples/` (PDFs gitignored; script is the source of truth)
- [x] **0.8** Project docs + first commit — Done 2026-08-14

## Phase 1 · Base Reading Assistant + Goal-Adaptive Reading

_Working order (dependency-driven): 1.1 → 1.2 → 1.3+1.4 → 1.5 → 1.6 → 1.7 → 1.8 → 1.9 → 1.10._

- [x] **1.1** PDF parsing pipeline → structured JSON (sections, sentences, offsets) — Done 2026-08-26: `app/core/` (layout → sections → segmentation → highlights), PyMuPDF span-walk builds `full_text` with offsets as a byproduct. Verified on all 10 sample papers: **0 offset mismatches, 0 sentences without bboxes**, 0.3–1.0s/paper. Sentence segmenter decided hand-rolled (see `docs/architecture.md`)
- [x] **1.2** FastAPI backend skeleton + parse/upload endpoint — Done 2026-08-26: `/api/reader` — upload, parse-sample, get, outline, pdf, list. Content-addressed disk cache (`PaperStore`); cached re-parse 0.01s vs 0.35s cold. 52 tests green
- [x] **1.3** React frontend skeleton + render a PDF — Done 2026-08-26: `react-pdf` 10 continuous-scroll viewer. **Renderer decision reversed** — `@allenai/pdf-components` pins pdf.js 2.14 (GHSA-wgrm-67xf-hhpq, arbitrary JS execution from a malicious PDF) and refuses React 18; rationale in `docs/architecture.md`. Overlay written in-house (~40 lines) since the parser already emits exact bboxes
- [x] **1.4** Basic reader UI (open, scroll, section outline) — Done 2026-08-26: sample picker + upload, continuous scroll, section outline with nesting, click-to-jump, scroll tracking. 64 vitest tests; verified in Chrome (18 assertions incl. highlight geometry + resize alignment), which caught 2 bugs jsdom could not
- [x] **1.5** Goal-selection modal (Skim / In-depth / Critique) — Done 2026-09-05: `lib/goals.js` is the single source of truth (stable backend-facing ids `skim`/`in-depth`/`critique` + a `criteria` line per goal that 1.6's ranking prompt will consume). `GoalModal` asks on every paper open — radiogroup semantics, arrow-key selection, roving tabindex, focus trap + restore, Escape/backdrop/"Not now" all dismiss without changing the goal. `GoalPicker` extracted for later changes. 96 vitest tests (was 64); verified in Chrome across all 6 flows, 0 console errors
- [x] **1.6** Goal-conditioned passage ranking (LLM prompt) — Done 2026-09-05: `app/llm/` (Gemini wrapper, structured output, retry honouring the server's `retryDelay`) + `core/reading_path.py` + `POST /papers/{id}/reading-path?goal=`. **Grounding enforced**: the model only returns indices into sentences we showed it, spans/text are echoed from the parse, unknown ids dropped and counted. On *Attention*: 306 candidates → skim 14 / in-depth 55 / critique 11, 0 hallucinated, all spans exact, goals near-disjoint (Jaccard 0.00–0.06). ~4-5s cold, 0.02s cached. 123 backend tests (was 52). Two real bugs found by running it: free tier is 5 req/min not 10, which silently dropped the front half of every paper, and partial results were being cached permanently — both fixed and documented in `docs/architecture.md`
- [x] **1.7** Render highlights / reading path overlay — Done 2026-09-05: `lib/readingPath.js` joins path items to the parse by `sentence_id` (the path carries no bboxes), importance 1-5 drives highlight intensity, `ReadingPathStatus` shows count / progress / errors / partial-path warning. Goal switching re-ranks and is instant on a cached goal. **Ranking now waits for the goal modal** — it used to fire on paper load, spending one call on the default goal and another on the one actually chosen. Verified in Chrome: skim 14/306 → 40 rects, critique 11/306 → 35, highlights pixel-aligned to the right text, 0 console errors. 129 frontend tests (was 96)
- [x] **1.8** Side-panel plain-language explanations (grounded) — Done 2026-09-21: the ranking prompt now also returns a plain-language restatement per passage, so the explanations cost **no extra LLM call** (same request, `RANKER_VERSION` → 2). `ExplanationPanel` lists the path in reading order; each entry pairs the explanation with the verbatim source sentence — **the explanation is never shown alone**, since it is generated prose and the sentence is the evidence for it. Clicking a passage jumps the viewer and draws a focus ring on that highlight. Verified on *Attention*: jargon expanded, every number preserved exactly (28.4, 41.8, 3.5 days, eight GPUs). 145 frontend + 127 backend tests
- [x] **1.9** Connect frontend ↔ backend (loading / streaming) — Done 2026-09-30: **fixed a real bug** — the Vite proxy answers with its own plain-text 500 when uvicorn is down, so a dead backend surfaced as "Request failed (500)" (reads like a backend bug) instead of "backend not reachable". A non-JSON 5xx is now read as unreachable, while a 5xx carrying FastAPI's `detail` stays a real backend error. Added a mount-time health check + `ConnectionBanner` carrying the uvicorn command, with live reconnect (no page reload), and a rate-limit explanation once ranking exceeds 8s. 156 frontend tests (was 145)
- [ ] **1.10** Test & polish on sample papers
- [ ] **1.11** ★ MILESTONE — working skim-vs-in-depth reading assistant demo

## Phase 2 · Citation Bridge (Cited-Span Localization)
- [ ] **2.1** Detect citation anchors → map to reference entries
- [ ] **2.2** Reference resolution via Semantic Scholar / arXiv API
- [ ] **2.3** Fetch cited paper full text (open-access; abstract fallback)
- [ ] **2.4** Segment cited paper into candidate passages
- [ ] **2.5** Localizer v1 — embedding retrieval (Specter2 / MiniLM)
- [ ] **2.6** CL-SciSumm eval harness (overlap F1, ROUGE, acc@k)
- [ ] **2.7** Evaluate localizer v1 (baseline)
- [ ] **2.8** Localizer v2 — LLM span selection + compare
- [ ] **2.9** (Optional) cross-encoder re-ranker fine-tune
- [ ] **2.10** Failure-mode analysis + taxonomy
- [ ] **2.11** UI: side-by-side view + fetch/open cited paper
- [ ] **2.12** UI: jump + highlight span; manual-correction fallback
- [ ] **2.13** ★ MILESTONE — click citation → land on cited passage demo

## Phase 3 · Agentic Citation Chat
- [ ] **3.1** Citation-intent data prep (SciCite)
- [ ] **3.2** Intent v1 — LLM prompt + evaluate (macro-F1)
- [ ] **3.3** (Optional) Intent v2 — fine-tune SciBERT + compare
- [ ] **3.4** Grounded-evidence tool (RAG over cited paper via localizer)
- [ ] **3.5** Bibliometrics tool (Semantic Scholar / OpenAlex)
- [ ] **3.6** Agent orchestration / tool routing
- [ ] **3.7** Chat UI panel over the bridge
- [ ] **3.8** Faithfulness evaluation (RAGAS-style)
- [ ] **3.9** Refusal / uncertainty handling
- [ ] **3.10** ★ MILESTONE — agentic chat over a citation demo

## Phase 4 · Evaluation, Write-up & Demo
- [ ] **4.1** Consolidate findings (localization / intent / faithfulness)
- [ ] **4.2** (Optional) small reader study (8–12 users)
- [ ] **4.3** Write project report / paper-style write-up
- [ ] **4.4** Final demo + slides
- [ ] **4.5** Polish repo (README, docs, reproducibility, release)
- [ ] **4.6** Future-work notes

---

_Bi-weekly: summarize recent `[x]` items for the progress email to Prof. Raghavachary._
