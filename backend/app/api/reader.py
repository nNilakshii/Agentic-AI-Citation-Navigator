"""Phase 1.2 — the reader API: get a PDF in, get a ParsedPaper back.

Everything is addressed by ``paper_id`` (``sha256`` of the PDF bytes), so
uploading the same paper twice is idempotent and costs one cache lookup.
"""

import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.api.limits import check_rank_budget
from app.cache import PaperStore
from app.core.goals import GOAL_SPECS
from app.core.pdf_parser import PARSER_VERSION, paper_id_for, parse_pdf
from app.core.reading_path import RANKER_VERSION, build_reading_path
from app.llm.client import LLMClient, LLMError, LLMNotConfigured, get_llm_client
from app.models.paper import ParsedPaper, PaperSummary, Section
from app.models.reading import ReadingGoal, ReadingPath

router = APIRouter()

#: Generous enough for a thesis, small enough that a bad upload fails fast.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

#: Sample papers fetched by ``scripts/fetch_sample_papers.py`` (task 0.7).
SAMPLES_DIR = Path(__file__).resolve().parents[3] / "data" / "samples"

_PDF_MAGIC = b"%PDF-"
_PAPER_ID = re.compile(r"^[0-9a-f]{64}$")


def get_store() -> PaperStore:
    """Injectable so tests can point the cache at a tmp directory."""
    return PaperStore()


@router.post("/papers", response_model=ParsedPaper, summary="Upload and parse a PDF")
async def upload_paper(
    file: UploadFile = File(...),
    force: bool = Query(False, description="Re-parse even if a cached parse exists"),
    store: PaperStore = Depends(get_store),
) -> ParsedPaper:
    """Parse an uploaded PDF into the canonical document model."""
    pdf_bytes = await file.read()
    _validate_pdf(pdf_bytes, file.filename or "upload.pdf")
    return await _parse_and_cache(
        pdf_bytes, file.filename or "upload.pdf", store, force=force
    )


@router.post(
    "/papers/samples/{name}",
    response_model=ParsedPaper,
    summary="Parse a local sample paper",
)
async def parse_sample(
    name: str,
    force: bool = Query(False, description="Re-parse even if a cached parse exists"),
    store: PaperStore = Depends(get_store),
) -> ParsedPaper:
    """Parse one of the ``data/samples`` PDFs — the dev path, no upload needed."""
    path = _sample_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"no sample named {name!r}")
    pdf_bytes = path.read_bytes()
    return await _parse_and_cache(pdf_bytes, path.name, store, force=force)


@router.get("/samples", response_model=list[str], summary="List local sample papers")
def list_samples() -> list[str]:
    if not SAMPLES_DIR.exists():
        return []
    return sorted(path.name for path in SAMPLES_DIR.glob("*.pdf"))


@router.get("/papers", response_model=list[PaperSummary], summary="List parsed papers")
def list_papers(store: PaperStore = Depends(get_store)) -> list[PaperSummary]:
    return [paper.summary() for paper in store.list_parsed(PARSER_VERSION)]


@router.get("/papers/{paper_id}", response_model=ParsedPaper, summary="Get a parse")
def get_paper(paper_id: str, store: PaperStore = Depends(get_store)) -> ParsedPaper:
    return _load_or_404(paper_id, store)


@router.get(
    "/papers/{paper_id}/outline",
    response_model=list[Section],
    summary="Get the section outline",
)
def get_outline(paper_id: str, store: PaperStore = Depends(get_store)) -> list[Section]:
    """The outline alone — what the reader sidebar (1.4) needs, without the text."""
    return _load_or_404(paper_id, store).sections


@router.get("/papers/{paper_id}/pdf", summary="Get the original PDF bytes")
def get_pdf(paper_id: str, store: PaperStore = Depends(get_store)) -> Response:
    """Serves the stored PDF so the frontend renders exactly what was parsed."""
    _check_paper_id(paper_id)
    pdf_bytes = store.load_pdf(paper_id)
    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail=f"no PDF for paper {paper_id}")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get(
    "/goals",
    summary="The reading goals and what each one surfaces",
)
def list_goals() -> list[dict]:
    """What the ranker means by each goal.

    Exposed so the frontend can stop hardcoding its copy (1.9) and so the
    wording driving the ranking is inspectable without reading the source.
    """
    return [
        {
            "id": spec.goal.value,
            "label": spec.label,
            "criteria": spec.criteria,
            "excludes": spec.exclude,
            "target_fraction": spec.target_fraction,
        }
        for spec in GOAL_SPECS.values()
    ]


@router.post(
    "/papers/{paper_id}/reading-path",
    response_model=ReadingPath,
    summary="Rank a paper's sentences for a reading goal (task 1.6)",
)
async def reading_path(
    request: Request,
    paper_id: str,
    goal: ReadingGoal = Query(description="skim | in-depth | critique"),
    force: bool = Query(False, description="Re-rank even if a cached path exists"),
    store: PaperStore = Depends(get_store),
    client: LLMClient = Depends(get_llm_client),
) -> ReadingPath:
    """Return the goal-conditioned reading path, ranking it if not cached.

    Ranking costs LLM quota and takes seconds, so results are cached per
    (paper, parser version, goal, ranker version) and re-served thereafter.
    """
    paper = _load_or_404(paper_id, store)

    if not force:
        cached = store.load_reading_path(paper_id, PARSER_VERSION, goal, RANKER_VERSION)
        if cached is not None:
            return cached

    # Only an actual LLM call costs budget. Checked after the cache lookup, so
    # browsing the pre-ranked samples is never rate limited.
    check_rank_budget(request)

    try:
        result = await build_reading_path(paper, goal, client)
    except LLMNotConfigured as error:
        # Configuration, not a transient fault — say so rather than a blank 502.
        raise HTTPException(status_code=503, detail=str(error)) from error
    except LLMError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    # A path missing a batch looks exactly like a complete one — the sentences
    # in it are real, there are just fewer of them. Caching it would turn a
    # transient rate limit into a permanently truncated reading path.
    if result.is_complete:
        store.save_reading_path(result)
    return result


@router.get(
    "/papers/{paper_id}/reading-path",
    response_model=ReadingPath,
    summary="The cached reading path, if one has been built",
)
def get_reading_path(
    paper_id: str,
    goal: ReadingGoal = Query(description="skim | in-depth | critique"),
    store: PaperStore = Depends(get_store),
) -> ReadingPath:
    """Read-only counterpart to the POST — never spends LLM quota."""
    _load_or_404(paper_id, store)
    cached = store.load_reading_path(paper_id, PARSER_VERSION, goal, RANKER_VERSION)
    if cached is None:
        raise HTTPException(
            status_code=404,
            detail=f"no reading path for {paper_id} and goal '{goal.value}'; "
            "POST to this URL to build one",
        )
    return cached


# --- helpers -----------------------------------------------------------


async def _parse_and_cache(
    pdf_bytes: bytes, filename: str, store: PaperStore, *, force: bool
) -> ParsedPaper:
    """Return the cached parse if there is one, otherwise parse and store it."""
    paper_id = paper_id_for(pdf_bytes)
    if not force:
        cached = store.load_parsed(paper_id, PARSER_VERSION)
        if cached is not None:
            return cached

    # Parsing is CPU-bound and takes seconds on a long paper; keep it off the
    # event loop so concurrent requests are not blocked behind it.
    try:
        paper = await run_in_threadpool(parse_pdf, pdf_bytes, filename)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    store.save_pdf(paper_id, pdf_bytes)
    store.save_parsed(paper)
    return paper


def _validate_pdf(pdf_bytes: bytes, filename: str) -> None:
    if not pdf_bytes:
        raise HTTPException(status_code=422, detail="uploaded file is empty")
    if len(pdf_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )
    if not pdf_bytes.startswith(_PDF_MAGIC):
        raise HTTPException(status_code=422, detail=f"{filename} is not a PDF")


def _sample_path(name: str) -> Path | None:
    """Resolve a sample name, refusing anything that escapes the samples dir."""
    candidate = (SAMPLES_DIR / name).resolve()
    samples_root = SAMPLES_DIR.resolve()
    if not candidate.is_relative_to(samples_root):
        return None
    return candidate if candidate.is_file() and candidate.suffix == ".pdf" else None


def _check_paper_id(paper_id: str) -> None:
    if not _PAPER_ID.match(paper_id):
        raise HTTPException(
            status_code=422, detail="paper_id must be a sha256 hex digest"
        )


def _load_or_404(paper_id: str, store: PaperStore) -> ParsedPaper:
    _check_paper_id(paper_id)
    paper = store.load_parsed(paper_id, PARSER_VERSION)
    if paper is None:
        raise HTTPException(status_code=404, detail=f"no parsed paper {paper_id}")
    return paper
