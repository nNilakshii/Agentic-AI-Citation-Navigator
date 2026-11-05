"""The text of a cited paper, as far as it could be obtained (task 2.3).

Localization (2.5) needs the cited paper's text to search. Not every cited
paper has one, so the result says honestly which rung of the fallback ladder
it reached (``docs/architecture.md``, Known risks):

    full text (a parsed PDF)  ->  abstract only  ->  unavailable

and, when it fell back, what was tried and why that failed. "Full text
unavailable" is a reported outcome, never a guess dressed as an answer.
"""

from enum import Enum

from pydantic import BaseModel, Field


class TextSource(str, Enum):
    FULL_TEXT = "full-text"
    ABSTRACT = "abstract"
    UNAVAILABLE = "unavailable"


class CitedText(BaseModel):
    citing_paper_id: str
    reference_id: str
    source: TextSource
    cited_paper_id: str | None = Field(
        default=None,
        description="Our parse of the cited PDF. Opens in the reader like any "
        "paper, so 2.11 can show it side by side.",
    )
    title: str | None = None
    fetched_from: str | None = Field(
        default=None, description="The URL the PDF came from"
    )
    abstract: str | None = None
    n_sentences: int = 0
    attempts: list[str] = Field(
        default_factory=list,
        description="What was tried before the result, and why each failed.",
    )
