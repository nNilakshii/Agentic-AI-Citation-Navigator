"""Citations in a paper, linked to its reference list (task 2.1).

The citation map is derived from a :class:`~app.models.paper.ParsedPaper`, not
part of it. Adding it to the parse would bump ``parser_version``, and every
cached reading path is keyed on that — so a change here would silently
invalidate rankings that cost API quota to build, including the ones the live
demo serves. As a separate artifact it versions independently
(``citation_version``).

Every anchor carries a character span into ``full_text``, the same currency as
everything else (``docs/architecture.md``), so the UI can make it clickable
through the existing offset -> bbox chain.
"""

from enum import Enum

from pydantic import BaseModel, Field


class CitationStyle(str, Enum):
    """How a paper cites. Decided from its reference list, not its body text."""

    NUMERIC = "numeric"  # [12], [3, 7], [1–4]
    AUTHOR_YEAR = "author-year"  # (Devlin et al., 2019), Devlin et al. (2019)
    UNKNOWN = "unknown"


class Reference(BaseModel):
    """One entry in the paper's reference list."""

    id: str = Field(description="Stable within a map, e.g. 'r012'")
    label: str | None = Field(
        default=None, description="The printed number for numeric styles, e.g. '12'"
    )
    text: str
    start_char: int
    end_char: int
    first_author: str | None = Field(
        default=None,
        description="Surname of the first author, as printed. Author-year "
        "citations resolve against this and `year`.",
    )
    year: str | None = Field(
        default=None, description="Four digits plus any disambiguating letter: '2018a'"
    )


class CitationAnchor(BaseModel):
    """One cited work at one place in the text.

    "(Dai et al., 2019; Radford et al., 2019)" is two anchors with two spans,
    because a reader clicks one work, not a bracket. A range like "[1–3]" is
    three anchors sharing one span, since the range has no finer place to point.
    """

    id: str = Field(description="Stable within a map, e.g. 'c0042'")
    text: str = Field(description="The citation as printed, e.g. 'Devlin et al., 2019'")
    start_char: int
    end_char: int
    sentence_id: str | None = None
    reference_id: str | None = Field(
        default=None,
        description="The entry this cites; None when no entry could be matched.",
    )


class CitationMap(BaseModel):
    """Every citation in a paper and the reference each one points at."""

    paper_id: str
    parser_version: str
    citation_version: str
    style: CitationStyle
    references_start: int | None = Field(
        default=None, description="Offset of the References heading, if found"
    )
    references_end: int | None = None
    references: list[Reference] = Field(default_factory=list)
    anchors: list[CitationAnchor] = Field(default_factory=list)

    @property
    def n_resolved(self) -> int:
        return sum(1 for a in self.anchors if a.reference_id is not None)
