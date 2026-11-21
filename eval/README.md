# eval

Evaluation harnesses, one per measured capability. Nothing runs until real data lands in
`data/` and the corresponding backend feature exists — see `docs/TASKS.md` for phase order.

- `localization/` — CL-SciSumm cited-span localization accuracy (Phase 2). Runnable:
  `backend/.venv/bin/python eval/localization/run_clscisumm_eval.py [--split dev|test] [--ranker random] [--save]`.
  Needs the corpus in `data/raw/scisumm-corpus` (see `clscisumm.py`). Aggregate results are
  committed in `localization/results/`; per-citance predictions go to `data/raw/` (ignored).
  LLM re-rank (2.8): add `--ranker hybrid --alpha 0.7 --rerank llm` (Gemini key needed; set
  `LLM_THINKING_BUDGET=1024` for the reported config); replies cached in `data/raw/llm-rerank-cache/`.
  Failure taxonomy (2.10): `analyze_failures.py <tag> --split dev [--sample 30] [--save]`
  reads those predictions and buckets every miss.
  Tests: `backend/.venv/bin/python -m pytest eval`.
- `intent/` — SciCite citation-intent classification (Phase 3). Data prep (3.1): `backend/.venv/bin/python eval/intent/scicite.py`
  prints the audit; needs the release in `data/raw/scicite` (see `scicite.py`). LLM classifier
  (3.2): `backend/.venv/bin/python eval/intent/run_scicite_eval.py --split dev --no-section
  [--sample 200] [--prompt-version N]`; test once with `--split test --no-section --save`.
  Gemini key needed; replies cached in `data/raw/intent-cache/`, per-row predictions in
  `data/raw/intent-predictions/`, aggregate results in `intent/results/`.
- `agent/` — tool routing (3.6): `backend/.venv/bin/python eval/agent/run_routing_eval.py [--save]`
  scores the model router and the keyword rules on 50 hand-labelled questions
  (`routing_questions.json`, written for this project). Gemini key needed.
- `chat_faithfulness/` — faithfulness of the chat's answers (3.8):
  `backend/.venv/bin/python eval/chat_faithfulness/run_faithfulness_eval.py [--save]`. Asks the
  real `/ask` path three questions per citation (19 citations with full text across the
  samples), judges every statement against its passage with a thinking Gemini judge, and
  tests the judge on planted errors. Everything is cached in `data/raw/faithfulness/`
  (statement records hold cited-paper text and stay there); aggregates in `results/`.

Tests for every harness: `backend/.venv/bin/python -m pytest eval`.
