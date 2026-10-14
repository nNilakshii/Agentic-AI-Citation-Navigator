# Deploying the reader

Written to be followed start to finish by someone who has not deployed anything before.

## What you are building

Two halves, two hosts, because they need different things:

| Half | Goes to | Why |
|---|---|---|
| Reader UI (`frontend/`) | **GitHub Pages** | Static files. Pages serves those for free. |
| API (`backend/`) | **Google Cloud Run** | Needs Python *and* holds the Gemini key, which must never reach a browser. |

The UI calls the API across the internet, so each has to be told about the other: the UI
is built with the API's address baked in (`VITE_API_BASE`), and the API is told which
origin may call it (`ALLOWED_ORIGINS`). Getting one of those wrong is the most common
failure, and both are covered below.

**Time:** about 40 minutes, most of it waiting for the first build.

---

## The thing that makes this demo reliable

Every sample paper is **already ranked**, and those rankings are committed to the repo
(`data/cache/parsed/`, `data/cache/reading_paths/`, ~4 MB). They are copied into the
image, so opening a sample paper makes **no LLM call at all** — any number of visitors
can browse all ten papers simultaneously without touching the API key or the quota.

Only an **upload** reaches the model. Two settings cap that:

- `RANK_BUDGET_PER_DAY` — what the whole deployment will spend in a day
- `RANK_LIMIT_PER_VISITOR` — one person's share of it

`/health` reports what is left. A cache hit never costs budget, so browsing is never
limited.

If you change the ranking prompt, `RANKER_VERSION` changes with it and every cached path
is invalidated. Rebuild them before deploying again:

```bash
cd backend && python scripts/qa_reading_paths.py
git add data/cache/parsed data/cache/reading_paths
```

---

# Part 1 · Backend to Google Cloud Run

> **Why not Hugging Face** (checked 2026-10-14): the new-Space page marks both Gradio and
> Docker as **Paid** — "Static Spaces stay free for everyone. To create a Space that runs
> on compute, subscribe to PRO." A Static Space serves files only, so it cannot run
> FastAPI. The Space frontmatter stays in README.md in case a PRO account appears later.

Cloud Run runs the same Dockerfile, scales to zero when nobody is using it, and bills
through ordinary Cloud Billing — which means the Google Cloud credits that could not
fund the Gemini prepay wallet **do** pay for it.

There are two ways in. **Use the Console route** unless you already have `gcloud`: it
needs nothing installed, and it redeploys automatically whenever you push to GitHub.

## 1A · Console route (no install, auto-deploys on push)

1. **console.cloud.google.com** → make sure the project selector at the top says
   **gen-lang-client-0514561442** (the project your API key belongs to)
2. Search for **Cloud Run** → **Deploy container** → **Service**
3. Choose **Continuously deploy from a repository** → **Set up with Cloud Build**
   - **Repository provider:** GitHub → authenticate → pick
     `nNilakshii/Agentic-AI-Citation-Navigator`
   - **Branch:** `^main$`
   - **Build type:** **Dockerfile**, path `/Dockerfile`
4. Back on the service form:
   - **Service name:** `aura-api`
   - **Region:** `us-central1`
   - **Authentication:** **Allow unauthenticated invocations** ← required, or the browser
     cannot reach it
5. Expand **Container(s), Volumes, Networking, Security** → **Variables & Secrets**:

   | Kind | Name | Value |
   |---|---|---|
   | Secret (or variable) | `GEMINI_API_KEY` | your key |
   | Variable | `ALLOWED_ORIGINS` | `https://<your-github-username>.github.io` |
   | Variable | `RANK_BUDGET_PER_DAY` | `15` |
   | Variable | `RANK_LIMIT_PER_VISITOR` | `3` |

   Prefer **Secret Manager** for the key if offered; a plain env var is acceptable on a
   private project but is visible to anyone with Console access.
6. **Create.** The first build takes 5–10 minutes — installing dependencies, then
   fetching the ten sample PDFs from arXiv.

Cloud Run injects `PORT`; the Dockerfile reads it, so there is nothing to configure.

## 1B · CLI route (if you would rather use a terminal)

Install the SDK once from `cloud.google.com/sdk/docs/install`, then:

```bash
gcloud auth login
gcloud config set project gen-lang-client-0514561442
gcloud run deploy aura-api \
  --source . --region us-central1 --allow-unauthenticated \
  --set-env-vars ALLOWED_ORIGINS=https://<your-github-username>.github.io,RANK_BUDGET_PER_DAY=15,RANK_LIMIT_PER_VISITOR=3 \
  --set-env-vars GEMINI_API_KEY=<your-key>
```

## 1.C Check it

Cloud Run gives you a URL like `https://aura-api-<hash>-uc.a.run.app`.

```bash
curl https://<your-service-url>/health
# {"status":"ok","rankings_left_today":15}

curl https://<your-service-url>/api/reader/samples
# ten .pdf filenames

curl https://<your-service-url>/api/reader/coverage
# each paper with ready: ["skim","in-depth","critique"]
```

That third one is the important check: every paper must list **all three goals**. If any
are empty, the cached paths did not reach the image and the demo will rank live.

**Write the service URL down.** Part 2 needs it.

## Cost

Cloud Run's always-free tier covers roughly 2M requests a month, and the service scales
to zero between visits. For a demo this is effectively free even before the credits. Set
a **budget alert** in Cloud Billing anyway.

---

# Part 2 · Frontend to GitHub Pages

## 2.1 Tell the UI where the API is

1. GitHub repo → **Settings** → **Secrets and variables** → **Actions**
2. The **Variables** tab (not Secrets) → **New repository variable**
   - **Name:** `VITE_API_BASE`
   - **Value:** `https://<username>-aura-citation-navigator.hf.space` — no trailing slash

A *variable*, not a secret: it is compiled into the public JavaScript either way, and it
is not sensitive.

## 2.2 Turn Pages on

**Settings** → **Pages** → **Source:** **GitHub Actions**

Not "Deploy from a branch" — `.github/workflows/deploy-frontend.yml` handles it.

## 2.3 Deploy

```bash
git commit --allow-empty -m "Trigger first Pages deploy"
git push origin main
```

Watch the **Actions** tab. The workflow runs the frontend tests, builds with the right
base path, and publishes. About three minutes.

Your site: `https://<your-github-username>.github.io/Agentic-AI-Citation-Navigator/`

---

# Part 3 · Check it works

Open the Pages URL:

1. **Ten papers listed**, each marked **ready** — the two halves are talking
2. Open **Attention Is All You Need**, confirm **Skim**
3. **Highlights appear immediately** ← the one to watch. More than a second or two means
   it is ranking live, so a cached path is missing from the image.
4. Switch to **Critique** — instantly different highlighting
5. Upload a PDF — works, takes a few seconds, counts against the budget

---

## When it doesn't work

| What you see | Cause | Fix |
|---|---|---|
| Page loads, no papers, CORS error in console | `ALLOWED_ORIGINS` wrong | Origin only: `https://you.github.io`. No path, no trailing slash. Then redeploy. |
| Blank page, 404s on `.js` files | Pages source wrong | Settings → Pages → Source = **GitHub Actions** |
| "The backend isn't running" banner | Cold start, or `VITE_API_BASE` wrong | Open the service URL directly to wake it. Check for a trailing slash. |
| Build fails on `fetch_sample_papers.py` | arXiv throttled the build | Re-run the build in Cloud Build |
| 503 "today's ranking budget is spent" | Expected once uploads use it up | Samples still work. Resets daily, or raise `RANK_BUDGET_PER_DAY`. |
| 403 from the service URL | Unauthenticated invocations not allowed | Cloud Run → service → Security → allow unauthenticated |
| Samples slow instead of instant | Cached paths missing | `git ls-files data/cache/reading_paths \| wc -l` — must be 30 |

## Updating later

```bash
git push origin main
```

That is all: the Pages workflow rebuilds the frontend, and Cloud Build rebuilds and
redeploys the backend from the same push.

## Known limits

- **Uploads do not persist.** Cloud Run containers are ephemeral and scale to zero, so an
  uploaded paper and its ranking vanish when the instance stops. The committed samples
  always survive.
- **The rate limit is in-memory.** It resets when the Space restarts and is keyed on
  `X-Forwarded-For`, which can be spoofed. It guards a quota, not access.
- **Cloud Run scales to zero.** The first request after an idle period pays a few seconds
  of cold start, once, not per paper.
- **Phase 2/3 evaluation will not fit** alongside the live app on one key. The CL-SciSumm
  harness is thousands of calls. Plan a separate key before that work.

## Other hosts

The Dockerfile reads `$PORT`, so it runs unchanged on any container host.

| Host | Cost | Cold start | Notes |
|---|---|---|---|
| **Google Cloud Run** | free tier + Cloud credits | ~2–5s | Cloud credits that cannot fund the Gemini prepay wallet *do* pay for this. Needs `gcloud`. |
| Hugging Face Spaces | **PRO only** | n/a | Free accounts get Static Spaces, which cannot run Python. |
| Fly.io | small free allowance | ~1–3s | Needs `flyctl`. |
| Render | free | **~50s** | Sleeps after 15 minutes — a poor first impression on a shared link. |
