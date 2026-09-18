"""What each reading goal means, in the words the ranker is given (task 1.6).

The backend owns the *prompt* wording because that is what determines the
ranking; the frontend's ``src/lib/goals.js`` owns the *display* wording. The
two share only the goal ids, and ``GET /api/reader/goals`` exposes this side so
the UI can stop hardcoding its copy when 1.9 wires them together.

`target_fraction` is the share of a paper's sentences a goal should surface. It
is a budget, not a quota — the ranker asks for that many and takes fewer if the
model finds fewer that qualify.
"""

from dataclasses import dataclass

from app.models.reading import ReadingGoal


@dataclass(frozen=True)
class GoalSpec:
    """The ranking contract for one goal."""

    goal: ReadingGoal
    label: str
    #: Dropped into the prompt as the definition of "relevant".
    criteria: str
    #: Told to the model so it does not merely re-rank everything.
    exclude: str
    #: Share of the paper's sentences to surface.
    target_fraction: float
    #: Floor and ceiling, so a 3-page note and a 40-page survey both behave.
    min_sentences: int
    max_sentences: int


GOAL_SPECS: dict[ReadingGoal, GoalSpec] = {
    ReadingGoal.SKIM: GoalSpec(
        goal=ReadingGoal.SKIM,
        label="Skim",
        criteria=(
            "The core claim of the paper, the single headline result with its "
            "number, the problem being solved, and the takeaway a reader could "
            "repeat afterwards."
        ),
        exclude=(
            "Method detail, derivations, hyperparameters, related-work summaries, "
            "and any sentence that only sets up another sentence."
        ),
        target_fraction=0.06,
        min_sentences=5,
        max_sentences=25,
    ),
    ReadingGoal.IN_DEPTH: GoalSpec(
        goal=ReadingGoal.IN_DEPTH,
        label="In-depth",
        criteria=(
            "How the method actually works, the key definitions and assumptions "
            "it rests on, the experimental setup, and the specific evidence "
            "behind each claim."
        ),
        exclude=(
            "Boilerplate, acknowledgements, and related work that does not bear "
            "on how this method works."
        ),
        target_fraction=0.18,
        min_sentences=12,
        max_sentences=70,
    ),
    ReadingGoal.CRITIQUE: GoalSpec(
        goal=ReadingGoal.CRITIQUE,
        label="Critique",
        criteria=(
            "Claims a reviewer would want to check: what the baselines are and "
            "what they leave out, ablations and what they fail to isolate, "
            "stated limitations, threats to validity, and places where a "
            "conclusion reaches further than the evidence shown."
        ),
        exclude=(
            "Uncontroversial background and method detail that raises no "
            "question of validity."
        ),
        target_fraction=0.10,
        min_sentences=8,
        max_sentences=40,
    ),
}


def spec_for(goal: ReadingGoal) -> GoalSpec:
    return GOAL_SPECS[goal]


def budget_for(goal: ReadingGoal, n_sentences: int) -> int:
    """How many sentences this goal should surface from a paper of this size."""
    spec = spec_for(goal)
    target = round(n_sentences * spec.target_fraction)
    # Never ask for more sentences than the paper has — a 4-sentence abstract
    # would otherwise get a floor of 5 and the model would pad.
    return max(min(target, spec.max_sentences), min(spec.min_sentences, n_sentences))
