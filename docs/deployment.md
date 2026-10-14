# Deploying the reader

Written to be followed start to finish by someone who has not deployed anything before.

## What you are building

Two halves, two hosts, because they need different things:

| Half | Goes to | Why |
|---|---|---|
| Reader UI (`frontend/`) | **GitHub Pages** | Static files. Pages serves those for free. |
| API (`backend/`) | **Hugging Face Space** | Needs Python *and* holds the Gemini key, which must never reach a browser. |

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

# Part 1 · Backend to Hugging Face

A Space is a **git repository that Hugging Face builds and runs**. There is no "connect
my GitHub repo" button for Docker Spaces — you push to the Space's own git remote. Your
project ends up with two remotes: `origin` (GitHub) and `hf` (Hugging Face).

## 1.1 Create the Space

1. Sign in at **huggingface.co**
2. Avatar (top right) → **New Space**
3. Fill in:
   - **Owner** — your username
   - **Space name** — `aura-citation-navigator`
   - **License** — MIT
   - **Select the Space SDK** — **Docker**, then the **Blank** template
   - **Space hardware** — **CPU basic · 2 vCPU · 16 GB · FREE**
   - **Visibility** — Public
4. **Create Space**

> **If something looks paid:** the SDK choice itself is free. What costs money is
> *upgraded hardware* (sometimes preselected — set it back to **CPU basic · FREE**) and
> **Dev Mode** (a toggle in Space settings — leave it off). If Docker genuinely is not
> available to you, see "Other hosts" at the end; the Dockerfile reads `$PORT` and runs
> anywhere.

You now have an empty Space at
`huggingface.co/spaces/<your-username>/aura-citation-navigator`.

## 1.2 Create a write token

The Space's git remote needs a token, not your account password.

1. **huggingface.co/settings/tokens**
2. **Create new token** → Token type **Write** → name it `aura-deploy`
3. **Copy it now.** It is shown once.

## 1.3 Push the code

```bash
cd ~/Documents/OPT_AURA/Agentic-AI-Citation-Navigator
git remote add hf https://huggingface.co/spaces/<your-username>/aura-citation-navigator
git push hf main
```

When prompted:
- **Username:** your Hugging Face username
- **Password:** the token from 1.2 — *not* your account password

If it refuses because the Space already has its own first commit:

```bash
git push hf main --force
```

Safe here: the only thing overwritten is Hugging Face's placeholder README.

The build starts automatically. It will fail without the key — that is next.

## 1.4 Set the key and the settings

Space page → **Settings** → **Variables and secrets**.

| Click | Name | Value |
|---|---|---|
| **New secret** | `GEMINI_API_KEY` | your key (the one in `.env`) |
| **New variable** | `ALLOWED_ORIGINS` | `https://<your-github-username>.github.io` |
| **New variable** | `RANK_BUDGET_PER_DAY` | `15` |
| **New variable** | `RANK_LIMIT_PER_VISITOR` | `3` |

Two things that matter:

- `GEMINI_API_KEY` **must be a Secret, not a Variable.** Variables are visible to anyone
  who can see the Space.
- `ALLOWED_ORIGINS` is an **origin** — scheme and host only. No path, no trailing slash.
  `https://you.github.io`, never `https://you.github.io/repo/`.

Adding a secret restarts the Space.

## 1.5 Watch the build

Space page → **Logs**. The first build takes **5–10 minutes**: installing dependencies,
then downloading the ten sample PDFs from arXiv.

You are waiting for:

```
Uvicorn running on http://0.0.0.0:7860
```

## 1.6 Check it

The Space URL uses **dashes**, not slashes:
`https://<username>-aura-citation-navigator.hf.space`

```bash
curl https://<username>-aura-citation-navigator.hf.space/health
# {"status":"ok","rankings_left_today":15}

curl https://<username>-aura-citation-navigator.hf.space/api/reader/samples
# ten .pdf filenames

curl https://<username>-aura-citation-navigator.hf.space/api/reader/coverage
# each paper with ready: ["skim","in-depth","critique"]
```

That third one is the important check: every paper must list **all three goals**. If any
are empty, the cached paths did not reach the image and the demo will rank live.

**Write the Space URL down.** Part 2 needs it.

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
| Page loads, no papers, CORS error in console | `ALLOWED_ORIGINS` wrong | Origin only: `https://you.github.io`. No path, no trailing slash. Then restart the Space. |
| Blank page, 404s on `.js` files | Pages source wrong | Settings → Pages → Source = **GitHub Actions** |
| "The backend isn't running" banner | Space asleep, or `VITE_API_BASE` wrong | Open the Space URL to wake it. Check for a trailing slash. |
| Build fails on `fetch_sample_papers.py` | arXiv throttled the build | Space Settings → **Factory rebuild** |
| 503 "today's ranking budget is spent" | Expected once uploads use it up | Samples still work. Resets daily, or raise `RANK_BUDGET_PER_DAY`. |
| Samples slow instead of instant | Cached paths missing | `git ls-files data/cache/reading_paths \| wc -l` — must be 30 |

## Updating later

```bash
git push origin main   # frontend — the Pages workflow runs
git push hf main       # backend  — the Space rebuilds
```

Both, if the change touches both.

## Known limits

- **Uploads do not persist.** Spaces' filesystem is ephemeral, so an uploaded paper and
  its ranking vanish on restart. The committed samples always survive.
- **The rate limit is in-memory.** It resets when the Space restarts and is keyed on
  `X-Forwarded-For`, which can be spoofed. It guards a quota, not access.
- **The Space sleeps** after inactivity. The first visit after that is slow once, not per
  paper.
- **Phase 2/3 evaluation will not fit** alongside the live app on one key. The CL-SciSumm
  harness is thousands of calls. Plan a separate key before that work.

## Other hosts

The Dockerfile reads `$PORT`, so it runs unchanged on any container host.

| Host | Cost | Cold start | Notes |
|---|---|---|---|
| **Google Cloud Run** | free tier + Cloud credits | ~2–5s | Cloud credits that cannot fund the Gemini prepay wallet *do* pay for this. Needs `gcloud`. |
| Hugging Face Spaces | free on CPU basic | wakes from sleep | The README frontmatter in this repo configures it. |
| Fly.io | small free allowance | ~1–3s | Needs `flyctl`. |
| Render | free | **~50s** | Sleeps after 15 minutes — a poor first impression on a shared link. |
