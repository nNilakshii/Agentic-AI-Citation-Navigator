# Deploying the reader

Two halves, two hosts. The frontend is a static bundle; the backend is Python and
holds the Gemini key, so it needs a real server and the key never reaches the browser.

| Half | Where | Why |
|---|---|---|
| Reader UI | GitHub Pages | Already have a Pages site; a static bundle is all it needs |
| API | Hugging Face Spaces (Docker) | Free, no card, built-in secrets, and where an ML demo is expected |

---

## The constraint everything else follows from

One Gemini key serves every visitor, and the free tier allows **20 requests a day** —
not per visitor, but in total, for the whole project. (There is also a 5-per-minute
limit, but the daily one binds first.)

A public demo therefore cannot rank papers on demand for an audience. Twenty uploads
empties the day for everyone, and a queue behind the per-minute limit is already
indistinguishable from the app being broken (see `build-log.md`, 1.9).

So the demo path makes **no LLM calls at all**:

- `data/cache/parsed/` and `data/cache/reading_paths/` are **committed** (~4 MB) and
  copied into the image. Every sample paper, every goal, already ranked.
- Only an upload reaches the model. `RANK_BUDGET_PER_DAY` caps what the deployment spends
  in total and `RANK_LIMIT_PER_VISITOR` caps one person's share; `/health` reports what is
  left. A cache hit never costs budget, so browsing is never limited.

Regenerate the committed caches after any prompt change (which bumps `RANKER_VERSION`
and invalidates them):

```bash
# 30 rankings against a 20-a-day quota: two sittings.
cd backend && python scripts/qa_reading_paths.py --max-calls 15
# ...then again tomorrow. Cached work is never redone.
git add data/cache/parsed data/cache/reading_paths
```

---

## Backend → Hugging Face Spaces

A Space is a git repo that HF builds. There is no "connect my GitHub repo" button
for Docker Spaces — you push to the Space's own remote, so this repo ends up with
two remotes (`origin` on GitHub, `hf` on Hugging Face).

The root `README.md` carries YAML frontmatter (`sdk: docker`, `app_port: 7860`)
because that is how a Space learns what it is. GitHub renders it as a small table;
that is the cost of deploying from one repo.

1. Create a Space: **Docker → Blank**, public, CPU basic (free).
2. Create a **write** access token at huggingface.co/settings/tokens.
3. Add the remote and push:

   ```bash
   git remote add hf https://huggingface.co/spaces/<user>/<space>
   git push hf main          # username = HF username, password = the token
   ```

4. Space **Settings → Variables and secrets**:

   | Name | Kind | Value |
   |---|---|---|
   | `GEMINI_API_KEY` | Secret | your key |
   | `ALLOWED_ORIGINS` | Variable | `https://<user>.github.io` |
   | `RANK_BUDGET_PER_DAY` | Variable | `15` |
   | `RANK_LIMIT_PER_VISITOR` | Variable | `3` |

4. Wait for the build, then check `https://<space>.hf.space/health` returns
   `{"status":"ok"}` and `/api/reader/samples` lists ten papers.

Notes:

- The image installs `requirements-prod.txt`, not `requirements.txt`.
  `sentence-transformers` pulls torch (~2 GB) and nothing in `app/` imports it yet —
  it is a Phase 2 dependency. Move it across when the localizer needs it.
- Sample PDFs are gitignored, so the build fetches them from arXiv with
  `scripts/fetch_sample_papers.py`. A fetch failure fails the build rather than
  shipping an app with an empty sample list.
- Spaces sleeps after inactivity. First request after a sleep is slow; the
  committed caches mean it is slow *once*, not per paper.

## Frontend → GitHub Pages

1. Repo **Settings → Pages → Source: GitHub Actions**.
2. Repo **Settings → Secrets and variables → Actions → Variables**, add
   `VITE_API_BASE` = `https://<space>.hf.space`. A variable, not a secret: it is
   baked into the bundle either way and is not sensitive.
3. Push to `main`. `.github/workflows/deploy-frontend.yml` runs the tests, builds
   with `BASE_PATH=/<repo>/`, and publishes.

`BASE_PATH` matters: a *project* Pages site is served from `/<repo>/`, so a bundle
built against `/` 404s on every asset.

## Checking it

```bash
curl https://<space>.hf.space/health          # {"status":"ok","rankings_left_today":15}
curl https://<space>.hf.space/api/reader/samples
```

Then open the Pages URL, pick a sample, confirm a goal, and confirm highlights appear
**immediately** — if a sample takes seconds, its cached path did not make it into the
image.

---

## Known limits of a public deployment

- **Uploads do not persist.** Spaces' filesystem is ephemeral, so an uploaded paper and
  its ranking vanish on restart. The committed samples always survive.
- **The rate limit is per process and in-memory.** It resets on restart and is keyed on
  `X-Forwarded-For`, which a determined visitor can spoof. It guards a quota, not access.
- **Twenty rankings a day, total.** That is the whole budget, shared by everyone. The
  pre-ranked samples are unaffected, but uploads will stop working once the day is spent
  and resume at the quota reset. If the demo gets real use, enable billing — pay-as-you-go
  Flash is fractions of a cent per ranking and makes this disappear.
- **Phase 2/3 evaluation will not fit.** The CL-SciSumm harness is far larger than the
  thirty calls that already strain this budget, and it draws on the same key as the live
  app. Plan a separate key before that work starts.
