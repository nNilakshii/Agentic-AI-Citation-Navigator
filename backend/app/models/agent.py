"""A chat answer about one citation, routed to tools (task 3.6)."""

from pydantic import BaseModel, Field

from app.models.bibliometrics import Bibliometrics
from app.models.evidence import GroundedAnswer
from app.models.localization import Localization


class CitationIntent(BaseModel):
    intent: str | None = Field(
        description="background, method or result; null if the model's reply "
        "was not one of them"
    )
    confidence: str
    citance: str = Field(description="The citing sentence that was classified")
    model: str | None = None


class ChatAnswer(BaseModel):
    """One part per tool the question was routed to, each with its own grounding.

    There is no combined prose answer on purpose: every part is a quote, a
    count, a ranked passage list or a label from a closed list (3.6).
    """

    question: str
    route: list[str] = Field(description="Tools run, most important first")
    routed_by: str = Field(description='"llm", or "rules" when no model was used')
    route_notes: list[str] = Field(default_factory=list)
    evidence: GroundedAnswer | None = None
    location: Localization | None = None
    intent: CitationIntent | None = None
    impact: Bibliometrics | None = None
    errors: dict[str, str] = Field(
        default_factory=dict,
        description="Tool name -> why it could not answer, in plain words",
    )
