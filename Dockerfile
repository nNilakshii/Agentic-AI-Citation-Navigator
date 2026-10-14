# Backend image for Hugging Face Spaces (Phase 1 deployment).
#
# Two things worth knowing:
#
# 1. It installs requirements-prod.txt, not requirements.txt — torch and the
#    unused LLM SDKs would add ~2 GB for code that does not run yet.
# 2. The sample papers are gitignored (16 MB of arXiv PDFs), so they are
#    fetched at build time by the script that already exists for local use.
#    The pre-computed parses and reading paths ARE committed, so every sample
#    is served without a single LLM call — which is what lets the demo survive
#    a 5-request-per-minute free tier with several visitors at once.

FROM python:3.12-slim

# HF Spaces runs as a non-root user with this uid.
RUN useradd -m -u 1000 app
WORKDIR /home/app

COPY --chown=app:app backend/requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY --chown=app:app backend/ ./backend/
COPY --chown=app:app data/ ./data/

USER app
ENV PYTHONPATH=/home/app/backend \
    PYTHONUNBUFFERED=1

# Fetch the sample PDFs the committed parses refer to. Network at build time
# only; a failure here should fail the build rather than ship an app whose
# sample list is empty.
RUN python backend/scripts/fetch_sample_papers.py

# Every host names the port differently: Spaces expects 7860, Cloud Run and
# Fly inject PORT, Render sets PORT too. Defaulting to 7860 keeps Spaces
# working with no configuration while letting the others override it.
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-7860}"]
