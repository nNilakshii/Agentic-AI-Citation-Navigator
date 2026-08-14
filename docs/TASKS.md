# AURA Citation Navigator — Task Tracker

Repo-native progress tracker. Kept in sync with git commits (see "How to update" below).
Mirror the high-level status into the Google Sheet whenever you want a shareable view.

**Status key:** `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked
Annotate each task with a short status/date, e.g. `— Done 2026-08-14` or `— Blocked: GROBID setup`.

## How to update (paste into Claude Code after a work session)
> "Look at my git commits since <date or last update>. Update docs/TASKS.md: check off
> completed tasks, mark in-progress ones `[~]`, and add today's date. Leave a one-line note
> on anything blocked. Don't change task text or IDs."

---

## Phase 0 · Setup & Foundations
- [x] **0.1** Create GitHub repo + project skeleton — Done 2026-08-14
- [x] **0.2** Set up local dev environment (Python venv + Node) — Done 2026-08-14: backend/.venv (Py 3.14.6, all requirements installed, pytest passes), frontend node_modules (Node 25.2.1, vite build passes)
- [x] **0.3** Get API keys & configure `.env` (LLM, Semantic Scholar, OpenAlex) — Done 2026-08-14: `.env` configured, all checks green via `backend/scripts/check_env.py`. LLM provider = **Gemini free tier** (key verified, 28 gemini-* models available); OpenAlex on the polite pool. Anthropic/Vertex deferred to Phase 2.8 where model quality is what's measured; Semantic Scholar key still worth requesting (slow to arrive, works unauthenticated meanwhile)
- [ ] **0.4** Literature review — reading tools (Semantic Reader, CiteRead, PaperMage)
- [ ] **0.5** Literature review — citation NLP (CL-SciSumm, SciCite, Specter2)
- [x] **0.6** Finalize architecture & stack (`docs/architecture.md`) — Done 2026-08-14: document model (char offsets + bboxes), stack table, backend layout, data flow, risks. Decided PyMuPDF-then-GROBID and Allen AI pdf-component-library
- [x] **0.7** Collect 5–10 sample arXiv papers for testing — Done 2026-08-14: `backend/scripts/fetch_sample_papers.py` fetches 10 curated open-access arXiv PDFs into `data/samples/` (PDFs gitignored; script is the source of truth)
- [x] **0.8** Set up Claude Code + CLAUDE.md + first commit — Done 2026-08-14: CLAUDE.md committed in 6677dc6, `.claude/` settings in place

## Phase 1 · Base Reading Assistant + Goal-Adaptive Reading
- [ ] **1.1** PDF parsing pipeline → structured JSON (sections, sentences, offsets)
- [~] **1.2** FastAPI backend skeleton + parse/upload endpoint — Skeleton (health check) done 2026-08-14, parse/upload endpoint still open
- [~] **1.3** React frontend skeleton + render a PDF — Skeleton (goal picker, backend ping) done 2026-08-14, PDF render still open
- [ ] **1.4** Basic reader UI (open, scroll, section outline)
- [ ] **1.5** Goal-selection modal (Skim / In-depth / Critique)
- [ ] **1.6** Goal-conditioned passage ranking (LLM prompt)
- [ ] **1.7** Render highlights / reading path overlay
- [ ] **1.8** Side-panel plain-language explanations (grounded)
- [ ] **1.9** Connect frontend ↔ backend (loading / streaming)
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
