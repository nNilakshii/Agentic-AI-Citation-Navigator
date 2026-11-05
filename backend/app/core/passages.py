"""Split a cited paper into candidate passages for localization (task 2.4).

A passage is a window of one to three consecutive sentences that stays inside
one section. Every window is emitted, overlapping — the localizer (2.5) picks
among them and must suppress near-duplicates of the same region in its top-k.

What is left out matters more than how the rest is cut, because a citing
sentence shares the most words with exactly the wrong places:

- **The reference list.** A citance naming a method matches the bibliography
  entry for it better than the passage that explains it. Found by the
  citation detector (2.1), or failing that by a section the parser titled
  "References" — in one fetched 1992 paper the first missed the heading and
  the whole bibliography became candidates.
- **Text after the references that is not an appendix.** The parser mistakes
  bibliography lines for headings ("7 Published as a conference paper at
  ICLR", an author list), and the reference list ends at the next heading —
  so after the references, only appendix-like headings are kept.
- **Acknowledgments.**
- **Sentences that are not prose**: author and affiliation lines, table and
  equation debris. Front matter is *not* dropped wholesale: when the parser
  finds no "Abstract" heading, the abstract lives there, and the abstract is
  among the most cited places in a paper.

Every exclusion is counted by reason, so a paper that lost most of its text
shows up in QA instead of quietly scoring badly.
"""

from __future__ import annotations

import re

from app.core.citations import build_citation_map
from app.core.segmentation import split_sentences
from app.models.paper import ParsedPaper, Sentence
from app.models.passage import Passage, PassageOrigin, PassageSet

#: Bumped when segmentation or exclusion changes.
PASSAGE_VERSION = "1"
MAX_WINDOW = 3
#: A window shorter than this says too little to be matched ("See Table 3.").
MIN_PASSAGE_CHARS = 40
MIN_WORDS = 4
#: Share of tokens that must be words. Table rows and equations fall below.
MIN_WORD_SHARE = 0.5

_APPENDIX_WORD = re.compile(
    r"^\s*(?:appendix|appendices|supplementary|supplemental)\b", re.IGNORECASE
)
#: "A Hyperparameter Settings", "B.2 Details", "C: Data" — case-sensitive, so
#: an author list ("Lutz Bornmann, ...") or a running header never matches.
_APPENDIX_LABEL = re.compile(r"^\s*[A-Z](?:\.\d+)*[.:]?\s+\S")
_REFERENCES_TITLE = re.compile(
    r"^\s*(?:\d+\.?\s+)?(?:references|bibliography)\s*$", re.IGNORECASE
)
_ACKNOWLEDGMENTS = re.compile(r"acknowledge?ments?", re.IGNORECASE)
_EMAIL = re.compile(r"\S+@\S+\.\w+")
_WORD = re.compile(r"^[A-Za-z][A-Za-z\-']*[A-Za-z]?[.,;:)]?$")


def passages_from_paper(paper: ParsedPaper) -> PassageSet:
    """Candidate passages from a parsed full text."""
    excluded: dict[str, int] = {}
    citations = build_citation_map(paper)
    refs_start = citations.references_start
    refs_end = citations.references_end
    if refs_start is None:
        refs_start, refs_end = _references_section(paper)
    titles = {s.id: s.title for s in paper.sections}
    starts = {s.id: s.start_char for s in paper.sections}

    def reason(sentence: Sentence) -> str | None:
        title = titles.get(sentence.section_id, "")
        if refs_start is not None and sentence.start_char >= refs_start:
            if sentence.start_char < refs_end:
                return "reference list"
            if not _looks_like_appendix(
                title, starts.get(sentence.section_id, -1), refs_end
            ):
                return "after the references, not an appendix"
        if _ACKNOWLEDGMENTS.search(title):
            return "acknowledgments"
        if not _is_prose(sentence.text):
            return "not prose"
        return None

    runs: list[list[Sentence]] = []
    current: list[Sentence] = []
    for sentence in paper.sentences:
        why = reason(sentence)
        if why:
            excluded[why] = excluded.get(why, 0) + 1
        breaks = why or (current and current[-1].section_id != sentence.section_id)
        if breaks and current:
            runs.append(current)
            current = []
        if not why:
            current.append(sentence)
    if current:
        runs.append(current)

    passages: list[Passage] = []
    for run in runs:
        for size in range(1, MAX_WINDOW + 1):
            for i in range(len(run) - size + 1):
                window = run[i : i + size]
                start, end = window[0].start_char, window[-1].end_char
                text = paper.full_text[start:end]
                if len(text.strip()) < MIN_PASSAGE_CHARS:
                    continue
                passages.append(
                    Passage(
                        id="",
                        text=text,
                        start_char=start,
                        end_char=end,
                        sentence_ids=[s.id for s in window],
                        section_title=titles.get(window[0].section_id),
                    )
                )

    passages.sort(key=lambda p: (p.start_char, p.end_char))
    for index, passage in enumerate(passages):
        passage.id = f"p{index:04d}"
    return PassageSet(
        paper_id=paper.paper_id,
        passage_version=PASSAGE_VERSION,
        origin=PassageOrigin.FULL_TEXT,
        passages=passages,
        excluded=excluded,
    )


def passages_from_abstract(abstract: str) -> PassageSet:
    """Candidate passages when only the abstract could be had (2.3's fallback).

    Offsets index into ``abstract`` itself.
    """
    spans = [(s, e) for s, e in split_sentences(abstract) if _is_prose(abstract[s:e])]
    passages: list[Passage] = []
    for size in range(1, MAX_WINDOW + 1):
        for i in range(len(spans) - size + 1):
            start, end = spans[i][0], spans[i + size - 1][1]
            text = abstract[start:end]
            if len(text.strip()) >= MIN_PASSAGE_CHARS:
                passages.append(
                    Passage(
                        id="",
                        text=text,
                        start_char=start,
                        end_char=end,
                        section_title="Abstract",
                    )
                )
    passages.sort(key=lambda p: (p.start_char, p.end_char))
    for index, passage in enumerate(passages):
        passage.id = f"p{index:04d}"
    return PassageSet(
        passage_version=PASSAGE_VERSION,
        origin=PassageOrigin.ABSTRACT,
        passages=passages,
    )


def _references_section(paper: ParsedPaper) -> tuple[int | None, int]:
    """The last section titled References or Bibliography, as (start, end)."""
    for section in reversed(paper.sections):
        if _REFERENCES_TITLE.match(section.title):
            return section.start_char, section.end_char
    return None, len(paper.full_text)


def _looks_like_appendix(title: str, section_start: int, refs_end: int) -> bool:
    """An appendix heading: "Appendix ...", "Supplementary ...", "A Details"."""
    if section_start < refs_end:
        return False
    return bool(_APPENDIX_WORD.match(title) or _APPENDIX_LABEL.match(title))


def _is_prose(text: str) -> bool:
    if _EMAIL.search(text):
        return False
    tokens = text.split()
    words = sum(1 for t in tokens if _WORD.match(t))
    return words >= MIN_WORDS and words / max(len(tokens), 1) >= MIN_WORD_SHARE
