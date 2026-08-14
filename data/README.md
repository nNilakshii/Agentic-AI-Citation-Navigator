# data

Sample papers & datasets. Large/generated files are gitignored (see root `.gitignore`):
`data/**/*.pdf`, `data/**/*.json`, and everything under `data/raw/` are not tracked.

- `samples/` — a handful of small, committed example papers/fixtures for dev and tests.
- `raw/` — scratch space for downloaded datasets (CL-SciSumm, SciCite). Gitignored entirely;
  populate locally via a fetch script once Phase 2/3 need it.
