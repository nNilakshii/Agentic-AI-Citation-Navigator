"""Which real paper each reference entry is (task 2.2).

A parsed reference is a string — "Ashish Vaswani, ... 2017. Attention is all
you need. In NIPS." Resolution turns it into an identity the rest of Phase 2
can act on: a Semantic Scholar id, an arXiv id or DOI, and above all a PDF that
2.3 can fetch.
"""

from enum import Enum

from pydantic import BaseModel, Field


class ResolutionMethod(str, Enum):
    """How an entry was matched — cheapest first, and the order they are tried."""

    S2_REFERENCES = "s2-references"  # the citing paper's own list on Semantic Scholar
    IDENTIFIER = "identifier"  # an arXiv id or DOI printed in the entry
    TITLE_SEARCH = "title-search"  # one search per entry, last resort


class ResolvedReference(BaseModel):
    reference_id: str = Field(description="The entry in the citation map, e.g. 'r012'")
    method: ResolutionMethod | None = None
    confidence: float = Field(
        default=0.0,
        description="Share of the matched title's words found in the entry text.",
    )
    s2_paper_id: str | None = None
    title: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None
    open_access_pdf: str | None = None
    contexts: list[str] = Field(
        default_factory=list,
        description="Citing sentences, as Semantic Scholar extracted them. Phase 3 "
        "intent classification can compare against these.",
    )
    intents: list[str] = Field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.s2_paper_id is not None or self.arxiv_id is not None

    @property
    def pdf_url(self) -> str | None:
        """Where 2.3 should fetch the full text.

        arXiv first: every arXiv paper is free to read, while Semantic Scholar
        lists an open-access PDF for far fewer (12 of 41 for Attention's
        references, against 30 with an arXiv id).
        """
        if self.arxiv_id:
            return f"https://arxiv.org/pdf/{self.arxiv_id}"
        return self.open_access_pdf


class ResolutionMap(BaseModel):
    paper_id: str
    parser_version: str
    citation_version: str
    resolver_version: str
    citing_s2_id: str | None = Field(
        default=None,
        description="The citing paper itself, if Semantic Scholar knows it",
    )
    items: list[ResolvedReference] = Field(default_factory=list)
    complete: bool = Field(
        default=True,
        description="False if any request failed, in which case some entries were "
        "never tried. An incomplete map is served but never cached.",
    )
