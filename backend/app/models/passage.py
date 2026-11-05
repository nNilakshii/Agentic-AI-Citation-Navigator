"""Candidate passages of a cited paper (task 2.4).

The localizer (2.5) ranks these against a citing sentence. A passage is a run
of one to three consecutive sentences inside one section: CL-SciSumm's gold
cited spans are mostly one or two sentences, and a lone sentence often reads
(and embeds) badly without its neighbour.
"""

from enum import Enum

from pydantic import BaseModel, Field


class PassageOrigin(str, Enum):
    FULL_TEXT = "full-text"
    ABSTRACT = "abstract"


class Passage(BaseModel):
    id: str = Field(description="Stable within a set, e.g. 'p0042'")
    text: str
    start_char: int = Field(description="Into the paper's full text, or the abstract")
    end_char: int
    sentence_ids: list[str] = Field(
        default_factory=list, description="Empty for abstract passages"
    )
    section_title: str | None = None


class PassageSet(BaseModel):
    paper_id: str | None = Field(
        default=None, description="None when only the abstract was available"
    )
    passage_version: str
    origin: PassageOrigin
    passages: list[Passage] = Field(default_factory=list)
    excluded: dict[str, int] = Field(
        default_factory=dict,
        description="Sentences left out, by reason — reported, not hidden.",
    )
