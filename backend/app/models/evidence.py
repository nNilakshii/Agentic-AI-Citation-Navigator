"""A question about a cited work, answered only from its text (task 3.4)."""

from enum import Enum

from pydantic import BaseModel, Field

from app.models.cited import TextSource
from app.models.localization import LocalizedPassage


class AnswerStatus(str, Enum):
    ANSWERED = "answered"
    #: The retrieved passages do not support an answer; nothing is guessed.
    INSUFFICIENT = "insufficient"
    #: There was no text of the cited work to search.
    UNAVAILABLE = "unavailable"


class Claim(BaseModel):
    text: str = Field(description="One statement of the answer")
    passage_id: str = Field(description="The passage it rests on")
    quote: str = Field(
        description="Words copied from that passage, checked verbatim, so the "
        "claim's support can be seen and verified"
    )


class GroundedAnswer(BaseModel):
    citing_paper_id: str
    anchor_id: str
    question: str
    status: AnswerStatus
    claims: list[Claim] = Field(default_factory=list)
    passages: list[LocalizedPassage] = Field(
        default_factory=list,
        description="What the model was shown, best first; claims cite these",
    )
    source: TextSource
    cited_paper_id: str | None = None
    model: str | None = None
    evidence_version: str
    dropped_claims: int = Field(
        default=0,
        description="Claims removed because their quote was not in the passage "
        "they cited. Reported, so a model that misquotes is visible.",
    )
    notes: list[str] = Field(default_factory=list)
