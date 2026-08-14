# CLAUDE.md — Project context for AURA Citation Navigator

This file gives Claude Code the context it needs to help build this project. Read it first.

## What we're building

**AURA Citation Navigator** — an adaptive research-paper reading assistant, built in three
layers on top of a base reader. Solo research project (USC, supervised by Prof. Saty
Raghavachary). The measurable research core is **cited-span localization**; the extension is
an **agentic citation chat**.

## The build order (IMPORTANT — respect the phases)

1. **Phase 1 — Base reading assistant + goal-adaptive reading.** A working reader that lets a
   user open a paper, pick a reading goal (Skim / In-depth / Critique), and see a
   goal-relevant highlighted reading path with plain-language explanations. *Build this first
   — everything else sits on it.*
2. **Phase 2 — Citation Bridge (cited-span localization).** Click a citation → resolve &
   fetch the cited paper → open side-by-side → jump to and highlight the exact passage being
   referenced. Evaluate localization accuracy on the CL-SciSumm benchmark.
3. **Phase 3 — Agentic Citation Chat.** A tool-using LLM over the bridge: citation-intent
   classification (SciCite), grounded explanations (RAG over the cited paper), and
   bibliometrics (Semantic Scholar / OpenAlex). Evaluate answer faithfulness.
4. **Phase 4 — Evaluation, write-up, demo.**

Do not jump ahead to Phase 2/3 code until Phase 1 works end-to-end.

## Architecture & stack

- `frontend/` — React reader UI (PDF rendering, highlights, side-by-side, chat panel).
  Prefer PaperCraft / Allen AI's pdf-component-library; react-pdf is an acceptable simpler start.
- `backend/` — Python + FastAPI. Handles PDF parsing, goal-conditioned ranking, cited-span
  localization, and the agentic chat.
- `eval/` — evaluation harnesses: CL-SciSumm (localization), SciCite (intent), RAGAS-style
  faithfulness for chat.
- `data/` — sample papers & datasets (large files are gitignored).
- `docs/` — architecture notes and the plan of action.

Key libraries: GROBID / PaperMage (parsing), sentence-transformers with Specter2 / MiniLM
(embeddings), OpenAI / Anthropic SDK (LLM), Semantic Scholar & OpenAlex APIs (scholarly data).

## Conventions

- Keep secrets in `.env` (already gitignored). Never hardcode or commit API keys.
- Python: type hints + docstrings; format with `black`; keep functions small and testable.
- Prefer cheap/local methods first (embeddings) and add LLM calls where they clearly help;
  cache API responses during development to save cost.
- Every LLM/agent answer that makes a factual claim should be grounded in retrieved text and
  cite its source span; surface uncertainty instead of guessing.
- Commit in small, logical chunks with clear messages. Update the progress tracker after each
  work session.

## Datasets & references

- **CL-SciSumm** (WING-NUS scisumm-corpus) — gold citance→cited-span annotations. Localization eval.
- **SciCite** — citation-intent labels (background / method / result). Intent eval.
- **Specter2**, **CiteRead** (IUI 2022), **PaperMage**, **Semantic Reader** — prior work to build on.

## How to help me

- I work ~2–3 hrs/day, Mon–Fri. Suggest small, completable chunks that fit a session.
- When I name a task from the tracker, scaffold or implement it, explain what you did briefly,
  and tell me how to run/test it.
- Flag risks (open-access limits, hallucination, scope creep) when relevant.
- First task on a fresh repo: create the folder structure above with minimal runnable
  skeletons for `frontend/` and `backend/`, plus `backend/requirements.txt`.
