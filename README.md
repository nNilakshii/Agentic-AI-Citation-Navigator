# AURA Citation Navigator

An adaptive research-paper reading assistant. AURA helps readers move through dense
academic papers by **goal** (skim vs. in-depth vs. critique), and turns citations into
living links: click a citation and AURA opens the cited paper side-by-side, jumps to the
**exact passage** being referenced, and lets you chat with that citation.

Solo research extension of the AURA project (USC, CSCI 599), supervised by
Prof. Saty Raghavachary.

## What it does

- **Goal-adaptive reading** — pick a reading goal; AURA highlights a relevant reading path.
- **Citation Bridge** — click a citation → fetch the cited paper → jump to the exact cited passage (*cited-span localization*).
- **Agentic Citation Chat** — ask *why* a paper was cited, what the cited passage says, and how influential it is (citation intent + grounded explanations + bibliometrics).

## Architecture (planned)

```
frontend/   React reader UI (PDF view, highlights, side-by-side, chat panel)
backend/    FastAPI: PDF parsing, goal ranking, cited-span localization, agentic chat
eval/       CL-SciSumm (localization) + SciCite (intent) evaluation harnesses
data/       sample papers & datasets (large files gitignored)
docs/       architecture notes, POA
```

## Tech stack

- **Frontend:** React (+ PaperCraft / pdf-component-library)
- **Backend:** Python, FastAPI
- **PDF parsing:** GROBID / PaperMage
- **Embeddings:** Specter2 / MiniLM (sentence-transformers)
- **LLM:** OpenAI / Anthropic API
- **Scholarly data:** Semantic Scholar API, OpenAlex
- **Eval:** CL-SciSumm, SciCite, RAGAS-style faithfulness checks

## Setup

```bash
# backend
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# frontend
cd ../frontend && npm install

# secrets
cp .env.example .env   # then fill in your API keys
```

## Roadmap

- **Phase 1** — Base reading assistant + goal-adaptive (skim vs. in-depth)
- **Phase 2** — Citation Bridge (cited-span localization) + evaluation
- **Phase 3** — Agentic Citation Chat (intent, grounded explanations, bibliometrics)
- **Phase 4** — Evaluation, write-up, demo

See `docs/` for the full plan of action.

## License

TBD
