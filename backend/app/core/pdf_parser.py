"""Phase 1.1 — PDF bytes in, :class:`ParsedPaper` out.

The pipeline:

    PDF bytes -> span walk (layout.py)   -> full_text + per-span offsets
              -> heading detection       -> sections
              -> sentence segmentation   -> sentence offsets
              -> offset->bbox mapping    -> sentence bboxes

Nothing here imports FastAPI: ``eval/`` calls this module directly, so evaluation
runs measure the algorithm rather than the transport. See ``docs/architecture.md``.
"""

import hashlib
import re

import pymupdf

from app.core.highlights import bboxes_for_span
from app.core.layout import LayoutText, extract_layout
from app.core.sections import detect_sections, section_id_at
from app.core.segmentation import split_sentences
from app.models.paper import ParsedPaper, PaperSource, Section, Sentence

#: Bump whenever parsing changes in a way that moves offsets. It is part of the
#: cache key, so a bump invalidates derived data instead of corrupting it.
PARSER_VERSION = "1"

#: arXiv stamps this down the side of page 1 of most of its PDFs.
_ARXIV_ID = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)

#: How far into the document to look for the title.
_TITLE_SEARCH_CHARS = 3000

_MIN_TITLE_CHARS = 8
_MAX_TITLE_CHARS = 250


def paper_id_for(pdf_bytes: bytes) -> str:
    """Content address of a PDF — the identity every cached artifact hangs off."""
    return hashlib.sha256(pdf_bytes).hexdigest()


def parse_pdf(pdf_bytes: bytes, filename: str) -> ParsedPaper:
    """Parse ``pdf_bytes`` into the canonical document representation.

    Args:
        pdf_bytes: The raw PDF file.
        filename: Recorded on the result for display; not used for parsing.

    Returns:
        A :class:`ParsedPaper` whose sentence offsets index into its own
        ``full_text``, and whose bboxes locate those same characters on the page.

    Raises:
        ValueError: If the bytes are not a readable PDF.
    """
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as error:  # pymupdf raises several types for bad input
        raise ValueError(f"could not open {filename} as a PDF: {error}") from error

    with doc:
        layout = extract_layout(doc)
        page_count = doc.page_count
        metadata_title = (doc.metadata or {}).get("title") or ""

    sections = detect_sections(layout.lines, layout.full_text)
    sentences = _build_sentences(layout, sections)

    return ParsedPaper(
        paper_id=paper_id_for(pdf_bytes),
        parser_version=PARSER_VERSION,
        source=PaperSource(
            filename=filename,
            title=_title(layout, metadata_title),
            arxiv_id=_arxiv_id(layout.full_text),
            page_count=page_count,
        ),
        full_text=layout.full_text,
        sections=sections,
        sentences=sentences,
    )


def _build_sentences(layout: LayoutText, sections: list[Section]) -> list[Sentence]:
    """Segment the text and attach each sentence's section, page and rectangles."""
    span_starts = [span.start for span in layout.spans]
    sentences: list[Sentence] = []

    for index, (start, end) in enumerate(split_sentences(layout.full_text)):
        bboxes = bboxes_for_span(layout.spans, span_starts, start, end)
        sentences.append(
            Sentence(
                id=f"s{index:05d}",
                text=layout.full_text[start:end],
                start_char=start,
                end_char=end,
                section_id=section_id_at(sections, start),
                page=bboxes[0].page if bboxes else 0,
                bboxes=bboxes,
            )
        )
    return sentences


def _arxiv_id(full_text: str) -> str | None:
    match = _ARXIV_ID.search(full_text, 0, _TITLE_SEARCH_CHARS * 2)
    return match.group(1) if match else None


def _title(layout: LayoutText, metadata_title: str) -> str | None:
    """Prefer a sane PDF metadata title; otherwise the largest type on page 1.

    LaTeX toolchains often leave the metadata title empty or set to the source
    filename, so the typographic fallback carries most real papers.
    """
    cleaned = " ".join(metadata_title.split())
    if _MIN_TITLE_CHARS <= len(
        cleaned
    ) <= _MAX_TITLE_CHARS and not cleaned.lower().endswith(
        (".dvi", ".tex", ".pdf", ".ps")
    ):
        return cleaned

    # The arXiv stamp is rotated down the side of page 1 and is often set larger
    # than the title itself, so it has to be excluded or it wins.
    candidates = [
        line
        for line in layout.lines
        if line.page == 0
        and line.start < _TITLE_SEARCH_CHARS
        and line.text.strip()
        and not _ARXIV_ID.search(line.text)
    ]
    if not candidates:
        return None

    largest = max(line.size for line in candidates)
    # A wrapped title is several consecutive lines set at the same size.
    title_lines = [
        line.text.strip()
        for line in candidates
        if line.size >= largest - 0.1 and len(line.text.strip()) > 1
    ]
    title = " ".join(title_lines).strip()
    return title[:_MAX_TITLE_CHARS] if len(title) >= _MIN_TITLE_CHARS else None
