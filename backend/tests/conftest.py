"""Shared fixtures. The synthetic PDF keeps the parser tests independent of
``data/samples/``, which is gitignored and may not be fetched yet."""

import pymupdf
import pytest

BODY_SIZE = 10.0
HEADING_SIZE = 13.0
TITLE_SIZE = 18.0

SAMPLE_BODY = (
    "Neural networks trained on citation data reach an F1 of 0.82 on this task. "
    "Prior work by Cohan et al. reports similar numbers under a different split. "
    "See Fig. 3 for the full curve, which flattens after ten epochs."
)


@pytest.fixture
def synthetic_pdf() -> bytes:
    """A two-page PDF with a title, two headings and wrapping body text."""
    doc = pymupdf.open()

    page = doc.new_page()
    page.insert_textbox(
        pymupdf.Rect(72, 72, 523, 130),
        "Localizing Cited Spans in Scientific Papers",
        fontsize=TITLE_SIZE,
        fontname="helv",
    )
    page.insert_textbox(
        pymupdf.Rect(72, 150, 523, 175),
        "1 Introduction",
        fontsize=HEADING_SIZE,
        fontname="hebo",
    )
    page.insert_textbox(
        pymupdf.Rect(72, 180, 523, 320),
        SAMPLE_BODY,
        fontsize=BODY_SIZE,
        fontname="helv",
    )

    page_two = doc.new_page()
    page_two.insert_textbox(
        pymupdf.Rect(72, 72, 523, 97),
        "2 Method",
        fontsize=HEADING_SIZE,
        fontname="hebo",
    )
    page_two.insert_textbox(
        pymupdf.Rect(72, 105, 523, 240),
        "We segment each document into sentences and embed them. "
        "The resulting index supports retrieval at interactive latency.",
        fontsize=BODY_SIZE,
        fontname="helv",
    )

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
