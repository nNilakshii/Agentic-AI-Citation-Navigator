# data

Sample papers & datasets. Large/generated files are gitignored (see root `.gitignore`):
`data/**/*.pdf`, `data/**/*.json`, and everything under `data/raw/` are not tracked.

- `samples/` — the dev/test corpus: 10 open-access arXiv papers chosen for dense citations.
  The PDFs themselves are gitignored; regenerate them with

      python backend/scripts/fetch_sample_papers.py

  The curated paper list lives in that script (the source of truth). Each run also writes
  `samples/manifest.json` with the resolved arXiv metadata (title, authors, PDF URL).
- `raw/` — scratch space for downloaded datasets (CL-SciSumm, SciCite). Gitignored entirely;
  populate locally via a fetch script once Phase 2/3 need it.
