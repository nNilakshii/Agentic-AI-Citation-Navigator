"""Phase 1.2 — the reader API: get a PDF in, get a ParsedPaper back.

Everything is addressed by ``paper_id`` (``sha256`` of the PDF bytes), so
uploading the same paper twice is idempotent and costs one cache lookup.
"""

import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.cache import PaperStore
from app.core.pdf_parser import PARSER_VERSION, paper_id_for, parse_pdf
from app.models.paper import ParsedPaper, PaperSummary, Section

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
