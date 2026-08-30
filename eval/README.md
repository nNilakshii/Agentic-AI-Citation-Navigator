# eval

Evaluation harnesses, one per measured capability. Nothing runs until real data lands in
`data/` and the corresponding backend feature exists — see `docs/TASKS.md` for phase order.

- `localization/` — CL-SciSumm cited-span localization accuracy (Phase 2).
- `intent/` — SciCite citation-intent classification (Phase 3).
- `chat_faithfulness/` — RAGAS-style groundedness/faithfulness for the agentic chat (Phase 3).

Each subfolder has a `run_*.py` stub: it defines the expected input/output contract now so
the metric code and the feature code can be built in parallel.
# eval

Evaluation harnesses, one per measured capability. Nothing runs until real data lands in
`data/` and the corresponding backend feature exists — see `CLAUDE.md` for phase order.

- `localization/` — CL-SciSumm cited-span localization accuracy (Phase 2).
- `intent/` — SciCite citation-intent classification (Phase 3).
- `chat_faithfulness/` — RAGAS-style groundedness/faithfulness for the agentic chat (Phase 3).

Each subfolder has a `run_*.py` stub: it defines the expected input/output contract now so
the metric code and the feature code can be built in parallel.
