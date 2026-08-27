"""The canonical parsed-paper representation.

Every span in this system is addressed as ``(paper_id, start_char, end_char)``
into :attr:`ParsedPaper.full_text`. Rankers (1.6), the localizer (2.5+) and the
chat agent (3.4) all consume and return spans in that form; the UI's only job is
to turn a span into a highlight via the sentence bounding boxes.

See ``docs/architecture.md`` for the rationale.
"""

from pydantic import BaseModel, Field


class BBox(BaseModel):
    """A rectangle on a page, in PDF points, origin top-left."""

    page: int = Field(description="0-based page index")
    x0: float
    y0: float
    x1: float
    y1: float


class Section(BaseModel):
    """A heading and the text beneath it, up to the next heading."""

    id: int = Field(description="Index into ParsedPaper.sections")
    title: str
    level: int = Field(description="1 for '3 Model', 2 for '3.1 Encoder', ...")
    start_char: int
    end_char: int
    page: int


class Sentence(BaseModel):
    """The unit of retrieval, ranking and evaluation.

    Sentence-level because CL-SciSumm's gold annotations are sentence-level, so
    the eval harness and the runtime representation agree without a conversion
    step. ``bboxes`` is a list because a sentence wraps across lines or columns.
    """

    id: str = Field(description="Stable within a parse, e.g. 's0042'")
    text: str
    start_char: int
    end_char: int
    section_id: int | None = None
    page: int
    bboxes: list[BBox] = Field(default_factory=list)


class PaperSource(BaseModel):
    """Where the document came from, and what we could infer about it."""

    filename: str
    title: str | None = None
    arxiv_id: str | None = None
    page_count: int = 0


class ParsedPaper(BaseModel):
    """Output of the Phase 1.1 parsing pipeline; cached on disk by paper_id."""

    paper_id: str = Field(description="sha256 of the PDF bytes")
    parser_version: str = Field(
        description="Bumped when parsing changes; part of the cache key, because "
        "shifted offsets would silently misalign every derived result."
    )
    source: PaperSource
    full_text: str
    sections: list[Section] = Field(default_factory=list)
    sentences: list[Sentence] = Field(default_factory=list)

    def summary(self) -> "PaperSummary":
        return PaperSummary(
            paper_id=self.paper_id,
            parser_version=self.parser_version,
            source=self.source,
            n_sections=len(self.sections),
            n_sentences=len(self.sentences),
            n_chars=len(self.full_text),
        )


class PaperSummary(BaseModel):
    """Lightweight view for listing endpoints — no full text, no sentences."""

    paper_id: str
    parser_version: str
    source: PaperSource
    n_sections: int
    n_sentences: int
    n_chars: int
