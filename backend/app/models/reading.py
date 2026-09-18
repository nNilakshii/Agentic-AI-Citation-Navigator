"""The reading path: what a goal-conditioned ranker returns (task 1.6).

A reading path is an *ordered subset* of a paper's sentences — the ones worth
reading for a stated goal — each carrying a span so the UI can highlight it
through the same offset -> bbox chain everything else uses
(``docs/architecture.md``).

Spans are echoed from the parse rather than recomputed: the ranker only ever
chooses among existing sentences, so a path can never point somewhere the
paper does not go. See ``app/core/reading_path.py`` for how that is enforced.
"""

from enum import Enum

from pydantic import BaseModel, Field


class ReadingGoal(str, Enum):
    """The three goals from task 1.5.

    These values are the wire format shared with the frontend's
    ``src/lib/goals.js`` — changing one without the other breaks the contract,
    which ``tests/test_goals.py`` guards against.
    """

    SKIM = "skim"
    IN_DEPTH = "in-depth"
    CRITIQUE = "critique"


class PathItem(BaseModel):
    """One sentence the ranker chose, and why."""

    sentence_id: str
    start_char: int
    end_char: int
    page: int
    section_id: int | None = None
    text: str
    importance: int = Field(
        ge=1, le=5, description="5 = read this first. Used for highlight intensity."
    )
    why: str = Field(
        description="One line on why this matters for the goal. Grounded in the "
        "sentence itself — shown in the 1.8 explanation panel."
    )


class ReadingPath(BaseModel):
    """A goal-conditioned ranking over one paper, cached on disk."""

    paper_id: str
    parser_version: str
    ranker_version: str = Field(
        description="Bumped when the prompt or selection logic changes, so a "
        "stale path is never served for new behaviour."
    )
    goal: ReadingGoal
    model: str = Field(description="The LLM that produced this, for reproducibility.")
    items: list[PathItem] = Field(default_factory=list)
    n_sentences_considered: int = Field(
        description="Denominator for the coverage figure shown in the UI."
    )
    n_hallucinated_ids: int = Field(
        default=0,
        description="Ids the model returned that are not in the paper. Dropped, "
        "never shown. Non-zero is a prompt-quality signal worth watching.",
    )
    n_batches: int = Field(default=1, description="LLM calls this path took.")
    n_batches_failed: int = Field(
        default=0,
        description="Batches that never returned, so part of the paper was "
        "never ranked. A path with any failure is served but never cached.",
    )

    @property
    def is_complete(self) -> bool:
        """Whether every part of the paper was actually ranked.

        An incomplete path is indistinguishable from a complete one by looking
        at it — the sentences it *does* contain are real. So it must not be
        cached, or a transient rate limit becomes a permanently truncated
        reading path for that paper and goal.
        """
        return self.n_batches_failed == 0
