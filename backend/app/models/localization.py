"""Where in the cited paper a citation points (task 2.5)."""

from pydantic import BaseModel, Field

from app.models.cited import TextSource
from app.models.passage import Passage


class LocalizedPassage(BaseModel):
    rank: int = Field(description="1 = best")
    score: float = Field(description="Cosine similarity to the citing sentence")
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
    notes: list[str] = Field(
        default_factory=list,
        description="Why the search was narrowed or empty, in plain words.",
    )
