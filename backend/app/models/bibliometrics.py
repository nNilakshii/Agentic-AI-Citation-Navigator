"""How influential a cited work is, and how the citing paper uses it (3.5)."""

from pydantic import BaseModel, Field


class CitationCount(BaseModel):
    source: str = Field(description="'semantic-scholar' or 'openalex'")
    citations: int
    influential: int | None = Field(
        default=None,
        description="Semantic Scholar only: citations that build on the work, "
        "not just mention it",
    )


class YearCount(BaseModel):
    year: int
    citations: int
    partial: bool = Field(
        default=False,
        description="The year was still in progress when counted: not a decline",
    )


class UseInPaper(BaseModel):
    """How often, and where, the citing paper cites this work."""

    mentions: int
    sections: list[str] = Field(
        default_factory=list, description="In order of first mention"
    )


class Bibliometrics(BaseModel):
    citing_paper_id: str
    reference_id: str
    title: str | None = None
    year: int | None = None
    venue: str | None = None
    fields_of_study: list[str] = Field(default_factory=list)
    counts: list[CitationCount] = Field(
        default_factory=list,
        description="One per database. They disagree — each indexes different "
        "literature — so both are shown with their source, never merged.",
    )
    by_year: list[YearCount] = Field(
        default_factory=list,
        description="OpenAlex citations per year, from the publication year on",
    )
    percentile: float | None = Field(
        default=None,
        description="OpenAlex: citation percentile among works of the same year "
        "and field (lower bound)",
    )
    in_this_paper: UseInPaper
    fetched_at: str = Field(description="When the counts were fetched (UTC, ISO)")
    notes: list[str] = Field(default_factory=list)
