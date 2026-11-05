"""Where in the cited paper a citation points (task 2.5)."""

from pydantic import BaseModel, Field

from app.models.cited import TextSource
from app.models.passage import Passage


class LocalizedPassage(BaseModel):
    rank: int = Field(description="1 = best")
    score: float = Field(
        description="Hybrid BM25 + embedding score, in standard deviations above "
        "the paper's average passage"
    )
    passage: Passage


class Localization(BaseModel):
    citing_paper_id: str
    anchor_id: str
    reference_id: str | None
    query: str = Field(description="The citing sentence, citation markers removed")
    source: TextSource = Field(
        description="Searched the full text, only the abstract, or nothing"
    )
    cited_paper_id: str | None = None
    model: str
    localizer_version: str
    results: list[LocalizedPassage] = Field(default_factory=list)
    clear_match: bool = Field(
        default=False,
        description="The top passage clearly leads the rest. On CL-SciSumm, right "
        "about 36% of the time versus 23% overall — a hint, not a guarantee.",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Why the search was narrowed or empty, in plain words.",
    )
