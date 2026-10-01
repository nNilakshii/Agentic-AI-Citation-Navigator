"""Goal-conditioned passage ranking (task 1.6).

Given a parsed paper and a reading goal, choose the sentences worth reading and
say why. The output is a :class:`ReadingPath` the UI highlights directly.

**The model selects, it never writes.** It is shown numbered sentences and can
only answer with those numbers; every id it returns is checked against the
paper and dropped if unknown, and the span and text of each item come from the
parse rather than the response. So a reading path cannot contain a sentence the
paper does not have, no matter what the model emits. That is the project's
grounding rule enforced at the one place it can be.

Long papers are split into batches, each ranked concurrently against the same
goal, then merged and trimmed to the goal's budget. Batches follow section
boundaries where they can, so a batch is a coherent stretch of the paper rather
than an arbitrary window.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.goals import budget_for, spec_for
from app.llm.client import LLMClient
from app.models.paper import ParsedPaper, Sentence
from app.models.reading import PathItem, ReadingGoal, ReadingPath

logger = logging.getLogger(__name__)

#: Bumped when the prompt or the selection logic changes. Part of the cache key.
RANKER_VERSION = "2"

#: Sentences per LLM call. Sized so a typical conference paper is a *single*
#: call: the free tier allows only 20 requests a *day*, and every extra batch
#: is both a chance to be rate-limited and a chance to lose part of the paper.
#: A 15-page paper is ~300 rankable sentences, well inside this.
BATCH_SIZE = 400

#: A sentence too short to carry a claim ("See Fig. 3.", "Proof.") is never a
#: useful destination, and filtering them before the call saves tokens.
MIN_SENTENCE_CHARS = 40

#: JSON schema the model must answer with. Native structured output means the
#: caller never has to parse prose.
SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "selections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {
                        "type": "integer",
                        "description": "The [n] label of the chosen sentence.",
                    },
                    "importance": {
                        "type": "integer",
                        "description": "5 = read first, 1 = marginal.",
                    },
                    "why": {
                        "type": "string",
                        "description": "One short clause, under 15 words.",
                    },
                    "plain": {
                        "type": "string",
                        "description": (
                            "The sentence restated in plain language, for a "
                            "reader outside this subfield. One or two "
                            "sentences. Say only what this sentence says."
                        ),
                    },
                },
                "required": ["n", "importance", "why", "plain"],
            },
        }
    },
    "required": ["selections"],
}

SYSTEM_PROMPT = (
    "You help a researcher read a paper for a stated purpose. You are given "
    "numbered sentences from one paper and you choose which of them that "
    "researcher should read.\n"
    "Rules:\n"
    "- Only ever answer with numbers shown in the list. Never invent one.\n"
    "- Choose whole sentences that carry the point on their own.\n"
    "- Prefer a sentence stating a result or a claim over one announcing that "
    "a result follows.\n"
    "- 'why' must describe what is in that sentence, not what you assume the "
    "paper says elsewhere.\n"
    "- 'plain' restates that one sentence for someone outside the subfield: "
    "expand the jargon, keep every number exactly as written, and add nothing "
    "the sentence does not say. If it is already plain, say it more simply "
    "rather than padding it.\n"
    "- Never speculate in 'plain'. It sits next to the original sentence in "
    "the UI, so a reader will notice immediately if it claims more.\n"
    "- Returning fewer than asked is correct when fewer qualify. Do not pad."
)


def _is_rankable(sentence: Sentence) -> bool:
    return len(sentence.text.strip()) >= MIN_SENTENCE_CHARS


def _batches(sentences: list[Sentence], size: int) -> list[list[Sentence]]:
    """Split into batches, preferring to break where a section does.

    A batch that ends mid-section makes the model judge a paragraph it cannot
    see the end of. Where a section boundary falls near the batch limit, break
    there instead; otherwise fall back to a hard split so one enormous section
    cannot produce one enormous batch.
    """
    if len(sentences) <= size:
        return [sentences] if sentences else []

    result: list[list[Sentence]] = []
    current: list[Sentence] = []
    for sentence in sentences:
        starts_section = (
            current
            and sentence.section_id is not None
            and sentence.section_id != current[-1].section_id
        )
        # Once a batch is ~70% full, the next section boundary is a good place
        # to stop rather than carrying on to an arbitrary cut.
        if current and (
            len(current) >= size or (starts_section and len(current) >= size * 0.7)
        ):
            result.append(current)
            current = []
        current.append(sentence)
    if current:
        result.append(current)
    return result


def _render_batch(paper: ParsedPaper, batch: list[Sentence]) -> str:
    """Number the sentences and label the section each belongs to."""
    titles = {section.id: section.title for section in paper.sections}
    lines: list[str] = []
    current_section: int | None = object()  # sentinel: never equal to an id
    for index, sentence in enumerate(batch):
        if sentence.section_id != current_section:
            current_section = sentence.section_id
            lines.append(f"\n## {titles.get(current_section, 'Untitled section')}")
        lines.append(f"[{index}] {sentence.text.strip()}")
    return "\n".join(lines)


def _build_prompt(
    paper: ParsedPaper, batch: list[Sentence], goal: ReadingGoal, want: int
) -> str:
    spec = spec_for(goal)
    title = paper.source.title or paper.source.filename
    return (
        f'Paper: "{title}"\n'
        f"Reading goal: {spec.label}\n\n"
        f"Select the sentences that match this goal.\n"
        f"Relevant means: {spec.criteria}\n"
        f"Not relevant: {spec.exclude}\n\n"
        f"Choose at most {want} sentences from the excerpt below. "
        f"Use the [n] labels exactly as shown.\n"
        f"--- excerpt ---{_render_batch(paper, batch)}"
    )


async def _rank_batch(
    client: LLMClient,
    paper: ParsedPaper,
    batch: list[Sentence],
    goal: ReadingGoal,
    want: int,
) -> tuple[list[PathItem], int]:
    """Rank one batch. Returns its items and how many ids had to be dropped."""
    payload = await client.generate_json(
        prompt=_build_prompt(paper, batch, goal, want),
        schema=SELECTION_SCHEMA,
        system=SYSTEM_PROMPT,
    )

    selections = (payload or {}).get("selections") or []
    items: list[PathItem] = []
    dropped = 0
    seen: set[int] = set()
    for selection in selections:
        index = selection.get("n")
        # The grounding check: an index must exist in the batch we showed.
        if not isinstance(index, int) or not 0 <= index < len(batch):
            dropped += 1
            continue
        if index in seen:
            continue
        seen.add(index)

        sentence = batch[index]
        importance = selection.get("importance")
        if not isinstance(importance, int):
            importance = 3
        items.append(
            PathItem(
                sentence_id=sentence.id,
                # Span and text come from the parse, never from the model.
                start_char=sentence.start_char,
                end_char=sentence.end_char,
                page=sentence.page,
                section_id=sentence.section_id,
                text=sentence.text,
                importance=max(1, min(5, importance)),
                why=str(selection.get("why") or "").strip()[:200],
                plain=str(selection.get("plain") or "").strip()[:600],
            )
        )
    return items, dropped


async def build_reading_path(
    paper: ParsedPaper, goal: ReadingGoal, client: LLMClient
) -> ReadingPath:
    """Rank a paper's sentences for a goal.

    Raises :class:`LLMError` if every batch fails — a partly-ranked paper is
    still useful, but a wholly unranked one should surface as an error rather
    than as an empty reading path the user cannot distinguish from "nothing is
    relevant".
    """
    candidates = [s for s in paper.sentences if _is_rankable(s)]
    if not candidates:
        return ReadingPath(
            paper_id=paper.paper_id,
            parser_version=paper.parser_version,
            ranker_version=RANKER_VERSION,
            goal=goal,
            model=client.model,
            items=[],
            n_sentences_considered=0,
            n_batches=0,
        )

    budget = budget_for(goal, len(candidates))
    batches = _batches(candidates, BATCH_SIZE)
    # Each batch gets a share of the budget proportional to its size, plus a
    # little slack so a batch holding most of the good material is not capped
    # below what the merge step would have taken from it.
    shares = [
        max(2, round(budget * len(batch) / len(candidates) * 1.3)) for batch in batches
    ]

    semaphore = asyncio.Semaphore(get_concurrency())

    async def run(batch: list[Sentence], want: int):
        async with semaphore:
            return await _rank_batch(client, paper, batch, goal, want)

    results = await asyncio.gather(
        *(run(batch, want) for batch, want in zip(batches, shares)),
        return_exceptions=True,
    )

    items: list[PathItem] = []
    hallucinated = 0
    errors: list[BaseException] = []
    for result in results:
        if isinstance(result, BaseException):
            errors.append(result)
            logger.warning("reading-path batch failed: %s", result)
            continue
        batch_items, dropped = result
        items.extend(batch_items)
        hallucinated += dropped

    if len(errors) == len(batches):
        # Re-raise the original rather than a generic wrapper: the API maps
        # LLMNotConfigured to "set your key" (503) and everything else to a
        # gateway error (502), and flattening them here would tell a user with
        # no API key that the upstream is broken.
        raise errors[0]

    # Merge: strongest first, and stable on document order within a tier so a
    # path reads top-to-bottom among equally important sentences.
    items.sort(key=lambda item: (-item.importance, item.start_char))
    del items[budget:]
    items.sort(key=lambda item: item.start_char)

    return ReadingPath(
        paper_id=paper.paper_id,
        parser_version=paper.parser_version,
        ranker_version=RANKER_VERSION,
        goal=goal,
        model=client.model,
        items=items,
        n_sentences_considered=len(candidates),
        n_hallucinated_ids=hallucinated,
        n_batches=len(batches),
        n_batches_failed=len(errors),
    )


def get_concurrency() -> int:
    from app.config import get_settings

    return max(1, get_settings().llm_max_concurrency)
