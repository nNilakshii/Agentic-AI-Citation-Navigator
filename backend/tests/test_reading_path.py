"""Goal-conditioned ranking (task 1.6).

No network: a fake :class:`LLMClient` stands in for Gemini, so these tests are
about the parts that decide whether a reading path is trustworthy — chiefly
that nothing the model says can put a span where the paper has none.
"""

import asyncio

import pytest

from app.core.goals import budget_for, spec_for
from app.core.reading_path import (
    BATCH_SIZE,
    MIN_SENTENCE_CHARS,
    RANKER_VERSION,
    _batches,
    _render_batch,
    build_reading_path,
)
from app.llm.client import LLMError
from app.models.paper import BBox, ParsedPaper, PaperSource, Section, Sentence
from app.models.reading import ReadingGoal


# --- fixtures ----------------------------------------------------------


def make_sentence(index: int, text: str, section_id: int = 0, page: int = 0):
    start = index * 1000
    return Sentence(
        id=f"s{index:05d}",
        text=text,
        start_char=start,
        end_char=start + len(text),
        section_id=section_id,
        page=page,
        bboxes=[BBox(page=page, x0=0, y0=0, x1=10, y1=10)],
    )


def make_paper(n_sentences: int = 10, sections: int = 2) -> ParsedPaper:
    sentences = [
        make_sentence(
            i,
            f"This is sentence number {i} and it is long enough to be ranked.",
            section_id=i % sections,
            page=i // 5,
        )
        for i in range(n_sentences)
    ]
    return ParsedPaper(
        paper_id="a" * 64,
        parser_version="1",
        source=PaperSource(filename="p.pdf", title="A Paper", page_count=3),
        full_text=" ".join(s.text for s in sentences),
        sections=[
            Section(
                id=i, title=f"Section {i}", level=1, start_char=0, end_char=10, page=0
            )
            for i in range(sections)
        ],
        sentences=sentences,
    )


class FakeLLM:
    """Returns whatever selections it is told to, and records the prompts."""

    def __init__(self, selections=None, *, error=None, model="fake-model"):
        self.model = model
        self._selections = selections if selections is not None else []
        self._error = error
        self.prompts: list[str] = []
        self.systems: list[str] = []
        self.calls = 0

    async def generate_json(self, *, prompt, schema, system=None):
        self.calls += 1
        self.prompts.append(prompt)
        self.systems.append(system)
        if self._error is not None:
            raise self._error
        if callable(self._selections):
            return {"selections": self._selections(prompt)}
        return {"selections": self._selections}


def build(paper, goal, client):
    return asyncio.run(build_reading_path(paper, goal, client))


# --- grounding: the property that matters ------------------------------


def test_spans_and_text_come_from_the_parse_not_the_model():
    paper = make_paper(5)
    # The model "quotes" text that is not in the paper. It must be ignored:
    # only the index is trusted.
    llm = FakeLLM([{"n": 2, "importance": 5, "why": "x", "text": "INVENTED"}])

    path = build(paper, ReadingGoal.SKIM, llm)

    assert len(path.items) == 1
    item = path.items[0]
    assert item.text == paper.sentences[2].text
    assert item.start_char == paper.sentences[2].start_char
    assert item.end_char == paper.sentences[2].end_char
    assert item.sentence_id == "s00002"


def test_out_of_range_indices_are_dropped_and_counted():
    paper = make_paper(5)
    llm = FakeLLM(
        [
            {"n": 0, "importance": 5, "why": "real"},
            {"n": 99, "importance": 5, "why": "hallucinated"},
            {"n": -1, "importance": 5, "why": "hallucinated"},
        ]
    )

    path = build(paper, ReadingGoal.SKIM, llm)

    assert [item.sentence_id for item in path.items] == ["s00000"]
    assert path.n_hallucinated_ids == 2


def test_non_integer_indices_are_dropped():
    paper = make_paper(5)
    llm = FakeLLM([{"n": "two", "importance": 5, "why": "nope"}])

    path = build(paper, ReadingGoal.SKIM, llm)

    assert path.items == []
    assert path.n_hallucinated_ids == 1


def test_every_item_points_at_a_real_sentence():
    paper = make_paper(30)
    llm = FakeLLM([{"n": i, "importance": 3, "why": "w"} for i in range(30)])

    path = build(paper, ReadingGoal.IN_DEPTH, llm)

    known = {s.id: s for s in paper.sentences}
    for item in path.items:
        assert item.sentence_id in known
        source = known[item.sentence_id]
        assert (item.start_char, item.end_char) == (source.start_char, source.end_char)


def test_duplicate_selections_are_taken_once():
    paper = make_paper(5)
    llm = FakeLLM([{"n": 1, "importance": 5, "why": "a"}] * 4)

    path = build(paper, ReadingGoal.SKIM, llm)

    assert len(path.items) == 1


# --- selection behaviour -----------------------------------------------


def test_items_are_returned_in_document_order():
    paper = make_paper(10)
    llm = FakeLLM(
        [
            {"n": 7, "importance": 5, "why": "w"},
            {"n": 1, "importance": 4, "why": "w"},
            {"n": 4, "importance": 5, "why": "w"},
        ]
    )

    path = build(paper, ReadingGoal.IN_DEPTH, llm)

    offsets = [item.start_char for item in path.items]
    assert offsets == sorted(offsets)


def test_the_budget_keeps_the_most_important_when_the_model_overshoots():
    paper = make_paper(100)
    # Every sentence selected, but importance rises with index.
    llm = FakeLLM([{"n": i, "importance": 1 + (i % 5), "why": "w"} for i in range(100)])

    path = build(paper, ReadingGoal.SKIM, llm)

    budget = budget_for(ReadingGoal.SKIM, 100)
    assert len(path.items) == budget
    # Nothing weak survived while something strong was cut.
    assert min(item.importance for item in path.items) == 5


def test_importance_is_clamped_into_range():
    paper = make_paper(5)
    llm = FakeLLM(
        [
            {"n": 0, "importance": 99, "why": "w"},
            {"n": 1, "importance": -3, "why": "w"},
            {"n": 2, "importance": None, "why": "w"},
        ]
    )

    path = build(paper, ReadingGoal.SKIM, llm)

    by_id = {item.sentence_id: item for item in path.items}
    assert by_id["s00000"].importance == 5
    assert by_id["s00001"].importance == 1
    assert by_id["s00002"].importance == 3  # missing -> neutral default


def test_short_sentences_are_never_candidates():
    paper = make_paper(3)
    paper.sentences.append(make_sentence(99, "See Fig. 3."))
    llm = FakeLLM([])

    path = build(paper, ReadingGoal.SKIM, llm)

    assert path.n_sentences_considered == 3
    assert len("See Fig. 3.") < MIN_SENTENCE_CHARS


def test_a_paper_with_nothing_rankable_returns_an_empty_path_without_calling_the_llm():
    paper = make_paper(0)
    paper.sentences = [make_sentence(0, "Short.")]
    llm = FakeLLM([{"n": 0, "importance": 5, "why": "w"}])

    path = build(paper, ReadingGoal.SKIM, llm)

    assert path.items == []
    assert path.n_sentences_considered == 0
    assert llm.calls == 0


def test_an_empty_selection_is_a_valid_answer():
    # "Nothing here matches the goal" must not be an error.
    path = build(make_paper(10), ReadingGoal.CRITIQUE, FakeLLM([]))

    assert path.items == []
    assert path.n_hallucinated_ids == 0


# --- goals differ ------------------------------------------------------


@pytest.mark.parametrize("goal", list(ReadingGoal))
def test_each_goal_puts_its_own_criteria_in_the_prompt(goal):
    llm = FakeLLM([])

    build(make_paper(10), goal, llm)

    spec = spec_for(goal)
    assert spec.criteria in llm.prompts[0]
    assert spec.exclude in llm.prompts[0]
    assert spec.label in llm.prompts[0]


def test_skim_asks_for_fewer_sentences_than_in_depth():
    assert budget_for(ReadingGoal.SKIM, 500) < budget_for(ReadingGoal.IN_DEPTH, 500)


def test_the_budget_never_exceeds_the_paper():
    # A four-sentence paper must not be given the goal's minimum of five.
    assert budget_for(ReadingGoal.SKIM, 4) <= 4


def test_the_goal_is_recorded_on_the_path():
    path = build(make_paper(10), ReadingGoal.CRITIQUE, FakeLLM([]))
    assert path.goal == ReadingGoal.CRITIQUE
    assert path.ranker_version == RANKER_VERSION
    assert path.model == "fake-model"


# --- batching ----------------------------------------------------------


def test_a_short_paper_is_one_call():
    llm = FakeLLM([])
    build(make_paper(10), ReadingGoal.SKIM, llm)
    assert llm.calls == 1


def test_a_long_paper_is_split_into_several_calls():
    llm = FakeLLM([])
    build(make_paper(BATCH_SIZE * 3), ReadingGoal.IN_DEPTH, llm)
    assert llm.calls >= 3


def test_batches_cover_every_sentence_exactly_once():
    sentences = [make_sentence(i, "x" * 60, section_id=i // 7) for i in range(500)]

    batches = _batches(sentences, BATCH_SIZE)

    flattened = [s.id for batch in batches for s in batch]
    assert flattened == [s.id for s in sentences]
    assert len(set(flattened)) == len(sentences)


def test_no_batch_exceeds_the_limit():
    sentences = [make_sentence(i, "x" * 60, section_id=i // 3) for i in range(700)]

    for batch in _batches(sentences, BATCH_SIZE):
        assert len(batch) <= BATCH_SIZE


def test_indices_are_per_batch_so_the_second_batch_resolves_correctly():
    # Regression guard: [0] in batch two must mean batch two's first sentence,
    # not the paper's. Getting this wrong silently highlights the wrong text.
    paper = make_paper(BATCH_SIZE * 2)
    llm = FakeLLM([{"n": 0, "importance": 5, "why": "w"}])

    path = build(paper, ReadingGoal.IN_DEPTH, llm)

    # Every batch picked its own index 0, so the result should be exactly the
    # first sentence of each batch — not the paper's first sentence repeated,
    # and not an offset into the wrong batch.
    candidates = [
        s for s in paper.sentences if len(s.text.strip()) >= MIN_SENTENCE_CHARS
    ]
    expected = {batch[0].id for batch in _batches(candidates, BATCH_SIZE)}
    assert {item.sentence_id for item in path.items} == expected
    assert len(expected) > 1, "this test needs a paper that actually batches"


def test_the_rendered_batch_labels_sections_and_numbers_from_zero():
    paper = make_paper(4, sections=2)

    rendered = _render_batch(paper, paper.sentences)

    assert "[0]" in rendered and "[3]" in rendered
    assert "## Section 0" in rendered


# --- failure handling --------------------------------------------------


def test_a_total_llm_failure_raises_rather_than_returning_an_empty_path():
    # An empty path means "nothing is relevant"; a failed call means "we don't
    # know". Collapsing the two would quietly show the reader a blank paper.
    llm = FakeLLM(error=LLMError("upstream exploded"))

    with pytest.raises(LLMError):
        build(make_paper(10), ReadingGoal.SKIM, llm)


def test_a_partial_failure_still_returns_what_succeeded():
    paper = make_paper(BATCH_SIZE * 3)
    state = {"calls": 0}

    class FlakyLLM(FakeLLM):
        async def generate_json(self, *, prompt, schema, system=None):
            state["calls"] += 1
            if state["calls"] == 1:
                raise LLMError("one batch failed")
            return {"selections": [{"n": 0, "importance": 4, "why": "w"}]}

    path = build(paper, ReadingGoal.IN_DEPTH, FlakyLLM())

    assert path.items, "surviving batches should still contribute"


def test_a_malformed_payload_is_tolerated():
    class WeirdLLM(FakeLLM):
        async def generate_json(self, *, prompt, schema, system=None):
            return {"unexpected": "shape"}

    path = build(make_paper(10), ReadingGoal.SKIM, WeirdLLM())

    assert path.items == []


def test_the_system_prompt_forbids_inventing_ids():
    llm = FakeLLM([])
    build(make_paper(10), ReadingGoal.SKIM, llm)
    assert "Never invent" in llm.systems[0]


def test_a_configuration_error_is_not_flattened_into_a_generic_failure():
    # Regression: LLMNotConfigured subclasses LLMError, and wrapping every
    # all-batches-failed case in a fresh LLMError told a user with no API key
    # that the upstream was broken (502) instead of that their key was missing
    # (503). The original exception type has to survive.
    from app.llm.client import LLMNotConfigured

    llm = FakeLLM(error=LLMNotConfigured("GEMINI_API_KEY is not set"))

    with pytest.raises(LLMNotConfigured):
        build(make_paper(10), ReadingGoal.SKIM, llm)
