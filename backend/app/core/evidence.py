"""Grounded evidence: answer a question about a cited work from its text (3.4).

Retrieval-augmented generation over the cited paper, built on the citation
bridge: the cited work's text (2.3), cut into passages (2.4), retrieved with
the hybrid ranker (2.7). Retrieval uses the question, plus the citing sentence
itself, so "what is this citation referring to?" finds what 2.12 would show.

Grounded by construction, as the reading path was (1.6):

- The model sees numbered passages and must answer in claims, each naming
  the passage it rests on and **quoting it**.
- Every quote is checked against the passage it names, verbatim up to
  whitespace and case. A claim that misquotes, or cites a passage it was not
  shown, is dropped — and the drop is counted, never hidden.
- If the model says the passages do not answer the question, or no claim
  survives the check, the answer is ``insufficient``: the tool says it cannot
  tell rather than guessing (CLAUDE.md: surface uncertainty).

The check proves each quote is really in the paper, not that the claim follows
from it; how often claims do is what the faithfulness evaluation (3.8) measures.
"""

from __future__ import annotations

import asyncio
import re

from app.core.embedding import Embedder
from app.core.localizer import cited_passages, rank_passages
from app.llm.client import LLMClient
from app.models.cited import TextSource
from app.models.evidence import AnswerStatus, Claim, GroundedAnswer
from app.models.localization import LocalizedPassage
from app.models.passage import Passage

#: Bumped when retrieval, the prompt or the checks change: part of the cache key.
EVIDENCE_VERSION = "1"
#: Passages retrieved for the question, and for the citing sentence.
QUESTION_K = 6
CITANCE_K = 2
#: A quote must be at least this long to count as evidence.
MIN_QUOTE_CHARS = 12
MAX_QUESTION_CHARS = 500

SYSTEM = (
    "You answer questions about one research paper using only the numbered "
    "passages from it that you are given. You never use outside knowledge, and "
    "you say when the passages do not answer the question."
)

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answerable": {
            "type": "boolean",
            "description": "False if the passages do not contain the answer.",
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "One sentence of the answer, in plain language.",
                    },
                    "passage": {
                        "type": "integer",
                        "description": "The [n] of the passage this sentence rests on.",
                    },
                    "quote": {
                        "type": "string",
                        "description": (
                            "5 to 25 words copied exactly from that passage "
                            "that support the sentence."
                        ),
                    },
                },
                "required": ["text", "passage", "quote"],
            },
        },
    },
    "required": ["answerable", "claims"],
}

_SPACE = re.compile(r"\s+")
# PDF text and model output disagree on dashes, quotes and ligatures; none of
# that changes what was said.
_FOLD = str.maketrans(
    {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "ﬁ": "fi", "ﬂ": "fl"}
)


async def answer_question(
    citing,
    anchor_id: str,
    citance: str,
    reference_id: str | None,
    question: str,
    resolution,
    store,
    scholar,
    downloader,
    openalex,
    embedder: Embedder,
    llm: LLMClient,
    cache_dir=None,
    spend=None,
) -> GroundedAnswer:
    """Retrieve from the cited work, ask the model, keep only checked claims.

    ``spend`` is called just before the model is: a budget check, so that a
    question about a paper with no text never costs quota.
    """
    result = GroundedAnswer(
        citing_paper_id=citing.paper_id,
        anchor_id=anchor_id,
        question=question,
        status=AnswerStatus.UNAVAILABLE,
        source=TextSource.UNAVAILABLE,
        evidence_version=EVIDENCE_VERSION,
    )
    if reference_id is None:
        result.notes.append("this citation is not linked to a reference entry (2.1)")
        return result

    # Fetching, parsing and embedding block; keep them off the event loop.
    cited, passage_set, notes = await asyncio.to_thread(
        cited_passages,
        citing,
        reference_id,
        resolution,
        store,
        scholar,
        downloader,
        openalex,
    )
    result.source = cited.source
    result.cited_paper_id = cited.cited_paper_id
    result.notes.extend(notes)
    if passage_set is None or not passage_set.passages:
        return result

    result.passages = await asyncio.to_thread(
        retrieve, question, citance, passage_set.passages, embedder, cache_dir
    )
    shown = {i + 1: r.passage for i, r in enumerate(result.passages)}
    if spend is not None:
        spend()
    reply = await llm.generate_json(
        prompt=build_prompt(question, citance, shown, cited.title),
        schema=ANSWER_SCHEMA,
        system=SYSTEM,
    )
    result.model = getattr(llm, "model", None)
    claims, dropped = check_claims(reply, shown)
    result.claims, result.dropped_claims = claims, dropped
    answerable = bool((reply or {}).get("answerable"))
    result.status = (
        AnswerStatus.ANSWERED if answerable and claims else AnswerStatus.INSUFFICIENT
    )
    if dropped:
        result.notes.append(
            f"{dropped} claim(s) dropped: their quote was not in the passage they cited"
        )
    return result


def retrieve(
    question: str,
    citance: str,
    passages: list[Passage],
    embedder: Embedder,
    cache_dir=None,
) -> list[LocalizedPassage]:
    """Best passages for the question, then for the citing sentence, no overlaps."""
    chosen: list[LocalizedPassage] = []
    for query, k in ((question, QUESTION_K), (citance, CITANCE_K)):
        if not query:
            continue
        for found in rank_passages(query, passages, embedder, k, cache_dir):
            p = found.passage
            if any(
                p.start_char < c.passage.end_char and c.passage.start_char < p.end_char
                for c in chosen
            ):
                continue
            chosen.append(found)
    for rank, found in enumerate(chosen, start=1):
        found.rank = rank
    return chosen


def build_prompt(
    question: str, citance: str, shown: dict[int, Passage], title: str | None
) -> str:
    lines = [
        f"Paper: {title or 'the cited paper'}",
        "",
        "A citing paper refers to it in this sentence (for context only; it is "
        "not part of the paper):",
        f'"{citance}"',
        "",
        "Passages from the paper:",
    ]
    for n, passage in shown.items():
        where = f" ({passage.section_title})" if passage.section_title else ""
        lines.append(f"[{n}]{where} {_SPACE.sub(' ', passage.text).strip()}")
    lines += [
        "",
        f"Question: {question}",
        "",
        "Answer in at most four claims. Each claim rests on exactly one passage "
        "and quotes 5 to 25 words from it, copied exactly. Use only these "
        "passages. If they do not answer the question, set answerable to false "
        "and return no claims.",
    ]
    return "\n".join(lines)


def check_claims(reply, shown: dict[int, Passage]) -> tuple[list[Claim], int]:
    """Keep the claims whose quote really is in the passage they cite."""
    kept: list[Claim] = []
    dropped = 0
    for raw in (reply or {}).get("claims") or []:
        n = raw.get("passage")
        passage = shown.get(n) if isinstance(n, int) else None
        # Models add a full stop or an ellipsis to a quote; neither is evidence.
        quote = (raw.get("quote") or "").strip().strip(".…\"' ")
        text = (raw.get("text") or "").strip()
        if (
            passage is None
            or not text
            or len(quote) < MIN_QUOTE_CHARS
            or _fold(quote) not in _fold(passage.text)
        ):
            dropped += 1
            continue
        kept.append(Claim(text=text, passage_id=passage.id, quote=quote))
    return kept, dropped


def _fold(text: str) -> str:
    return _SPACE.sub(" ", text.translate(_FOLD)).strip().lower()
