"""Recover a paper's section structure from typographic and lexical evidence.

PyMuPDF gives no document outline for a typical arXiv PDF, so headings are
inferred from the laid-out lines: numbering ("3.1 Encoder"), a known section name
("Abstract", "References"), or type set larger/bolder than the body.

This is deliberately a heuristic. GROBID does it properly, and ``docs/architecture.md``
defers that to Phase 2.1 where structured reference parsing is the actual task.
The consumer of this — the reader outline (1.4) and section-aware ranking (1.6) —
degrades gracefully when a heading is missed: text simply belongs to the previous
section.
"""

import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass

from app.core.layout import LaidOutLine
from app.models.paper import Section

#: Text before the first detected heading — title, authors, abstract on page 1.
FRONT_MATTER_TITLE = "Front matter"

#: Longest a line can be and still plausibly be a heading.
_MAX_HEADING_CHARS = 90

#: "3.1 Encoder". The title must begin with a letter: without that, a table row
#: of numbers ("84.2 91.1 85.1 91.8") reads as section 84, subsection 2.
_NUMBERED = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+([A-Za-z][\w\-].*)$")

#: A bare section number. LaTeX frequently typesets "3" and "Model Architecture"
#: as separate blocks, so these are merged with the heading that follows.
_SECTION_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s*$")

#: Headings that carry no number in most templates. Deliberately excludes bare
#: "Model" / "Dataset" / "Data": those are table column headers far more often
#: than they are sections, and a genuine one is almost always numbered.
_NAMED = re.compile(
    r"^\s*(abstract|introduction|related\s+work|background|motivation|"
    r"method(?:s|ology)?|approach|"
    r"experiment(?:s|al\s+setup)?|evaluation|result(?:s|s\s+and\s+discussion)?|"
    r"analysis|ablation(?:s|\s+stud(?:y|ies))?|"
    r"discussion|limitations?|future\s+work|conclusions?(?:\s+and\s+future\s+work)?|"
    r"acknowledge?ments?|references|bibliography|appendix(?:\s+[a-z0-9].*)?)\s*$",
    re.IGNORECASE,
)

#: The rotated stamp down the side of page 1 of an arXiv PDF. It is the largest
#: type on the page in many templates, so it must be excluded from both heading
#: detection and title detection or it wins both.
_ARXIV_STAMP = re.compile(r"arXiv:\s*\d{4}\.\d{4,5}", re.IGNORECASE)

#: Section bodies end in prose; a heading almost never does.
_ENDS_LIKE_PROSE = re.compile(r"[.,;:]$")

#: A sentence boundary inside the line — a caption or body text that happened to
#: be set in heading-like type, e.g. "Table 4: Top: changing window size. Bot-".
_CONTAINS_PROSE = re.compile(r"[.!?)]\s+[A-Za-z]")

#: A paper may skip at most this many section numbers before we stop believing a
#: number is a section number at all. Tolerates one missed heading; rejects the
#: "93.1" of a results table.
_MAX_SECTION_SKIP = 2

#: Highest plausible first section number in a paper with no numbering seen yet.
_MAX_FIRST_SECTION = 20

#: A heading is words, not figures — used to reject numeric table rows.
_LETTERS = re.compile(r"[A-Za-z]")


def detect_sections(lines: list[LaidOutLine], full_text: str) -> list[Section]:
    """Segment the document into sections covering ``full_text`` end to end.

    Args:
        lines: Laid-out lines in reading order, from :func:`~app.core.layout.extract_layout`.
        full_text: The string the line offsets index into.

    Returns:
        Contiguous, non-overlapping sections. Always covers ``[0, len(full_text))``
        so that every sentence lands in exactly one section.
    """
    if not full_text:
        return []

    body_size = _body_size(lines)
    headings = _headings(lines, body_size)

    starts: list[_Heading] = []
    if not headings or headings[0].start > 0:
        page = lines[0].page if lines else 0
        starts.append(_Heading(start=0, title=FRONT_MATTER_TITLE, level=1, page=page))
    starts.extend(headings)

    sections: list[Section] = []
    for index, heading in enumerate(starts):
        start, title, level, page = (
            heading.start,
            heading.title,
            heading.level,
            heading.page,
        )
        end = starts[index + 1].start if index + 1 < len(starts) else len(full_text)
        sections.append(
            Section(
                id=index,
                title=title,
                level=level,
                start_char=start,
                end_char=end,
                page=page,
            )
        )
    return sections


def _body_size(lines: list[LaidOutLine]) -> float:
    """The dominant font size, weighted by how much text is set in it.

    Weighted by character count rather than line count so that a title page full
    of short large-type lines cannot outvote the body text.
    """
    weights: Counter[float] = Counter()
    for line in lines:
        weights[line.size] += len(line.text)
    if not weights:
        return 0.0
    return weights.most_common(1)[0][0]


@dataclass
class _Heading:
    """A detected heading, after bare section numbers have been merged in."""

    start: int
    title: str
    level: int
    page: int
    number: str | None = None
    #: Index of the last line consumed, so a wrapped continuation is not also
    #: emitted as a section of its own.
    last_line: int = -1


def _headings(lines: list[LaidOutLine], body_size: float) -> list[_Heading]:
    """Detect headings, merging split numbers and dropping the title block.

    Three corrections happen here, all learned from real papers:

    * A paper's title and author list are the largest type in the document, so
      the typographic rule fires on them. They are front matter, not sections —
      so size-only detections are ignored until the first *named* ("Abstract")
      or *numbered* ("1 Introduction") heading shows the body has begun.
    * LaTeX often emits the section number and its title as separate blocks, so
      a bare "3" is carried forward and merged with the line that follows it.
    * In two-column templates a long heading wraps, and the continuation line is
      itself heading-like. It is folded into the heading above rather than
      starting a section of its own.
    """
    kinds = [_heading_kind(line, body_size) for line in lines]
    headings: list[_Heading] = []
    numbering = _NumberingGuard()
    body_started = False
    consumed = -1  # last line index already folded into a heading

    for index, (line, kind) in enumerate(zip(lines, kinds)):
        if kind is None or index <= consumed:
            continue

        heading = (
            _merge_with_next(line, lines, kinds, index)
            if kind == "number_only"
            else _Heading(
                start=line.start,
                title=line.text.strip(),
                level=_level(line.text.strip()),
                page=line.page,
                number=_number_of(line.text.strip()),
                last_line=index,
            )
        )
        if heading is None or not numbering.accepts(heading.number):
            continue

        if kind in ("named", "numbered", "number_only"):
            body_started = True
        elif not body_started:
            continue

        _absorb_wrapped_lines(heading, lines, kinds, body_size)
        consumed = heading.last_line
        headings.append(heading)
    return headings


def _absorb_wrapped_lines(
    heading: _Heading,
    lines: list[LaidOutLine],
    kinds: list[str | None],
    body_size: float,
) -> None:
    """Fold a heading's wrapped continuation lines into its title.

    A continuation is the immediately following line, set in the same type, that
    was detected only on typography — it carries no number and no section name of
    its own, which is exactly what a second line of one heading looks like.
    """
    index = heading.last_line
    anchor = lines[index]
    while index + 1 < len(lines):
        following = lines[index + 1]
        if kinds[index + 1] != "typographic":
            break
        if following.page != anchor.page:
            break
        if following.size != anchor.size or following.bold != anchor.bold:
            break
        heading.title = f"{heading.title} {following.text.strip()}"
        index += 1
    heading.last_line = index


class _NumberingGuard:
    """Rejects numbers that cannot be section numbers, given what came before.

    Section numbering runs 1, 2, 3 … so a "93.1" appearing after section 5, or a
    "1.10" appearing after section 4, is a table cell rather than a heading —
    a distinction typography alone cannot make, since both are set in bold.
    """

    def __init__(self) -> None:
        self._max_major: int | None = None

    def accepts(self, number: str | None) -> bool:
        """Whether ``number`` ("3", "3.1") can be the next section number."""
        if number is None:
            return True  # unnumbered headings are not this rule's business
        major = int(number.split(".")[0])

        if self._max_major is None:
            plausible = major <= _MAX_FIRST_SECTION
        else:
            plausible = self._max_major <= major <= self._max_major + _MAX_SECTION_SKIP

        if plausible:
            self._max_major = max(self._max_major or 0, major)
        return plausible


def _merge_with_next(
    number_line: LaidOutLine,
    lines: list[LaidOutLine],
    kinds: list[str | None],
    index: int,
) -> _Heading | None:
    """Attach a bare section number to the title on the following line."""
    if index + 1 >= len(lines):
        return None
    title_line = lines[index + 1]
    title = title_line.text.strip()

    # The next line need not be a heading in its own right — the number's
    # typography vouches for it — but it must read as a title. Requiring it to
    # start with a letter is what stops a table row ("72.1" above "92.7", or
    # "80.0" above "−abstract") merging into a section.
    looks_like_title = (
        title[:1].isalpha()
        and len(title) <= _MAX_HEADING_CHARS
        and not _ENDS_LIKE_PROSE.search(title)
        and not _CONTAINS_PROSE.search(title)
        and _is_wordy(title)
    )
    if not looks_like_title:
        return None

    number = number_line.text.strip().rstrip(".")
    return _Heading(
        start=number_line.start,
        title=f"{number} {title}",
        level=number.count(".") + 1,
        page=number_line.page,
        number=number,
        last_line=index + 1,
    )


def _number_of(text: str) -> str | None:
    """The section number of a numbered heading, or ``None`` if unnumbered."""
    match = _NUMBERED.match(text)
    return match.group(1) if match else None


def _heading_kind(line: LaidOutLine, body_size: float) -> str | None:
    """Classify a line as a heading and say what made it one."""
    text = line.text.strip()
    if not text or len(text) > _MAX_HEADING_CHARS:
        return None
    if _ARXIV_STAMP.search(text):
        return None

    set_apart = line.bold or line.size > body_size + 0.4
    if _SECTION_NUMBER.match(text) and set_apart:
        return "number_only"

    if _ENDS_LIKE_PROSE.search(text) or _CONTAINS_PROSE.search(text):
        return None
    # A named heading must also be capitalised and set apart: "method" in lower
    # case at body size is a label inside a figure, not a section.
    if _NAMED.match(text) and text[:1].isupper() and set_apart:
        return "named"
    if _NUMBERED.match(text) and set_apart:
        return "numbered"
    # Unnumbered but clearly set apart, short enough to be a label, and made of
    # words rather than figures.
    if (
        line.size > body_size + 0.4
        and (line.bold or line.size > body_size + 1.5)
        and len(text) <= 60
        and _is_wordy(text)
    ):
        return "typographic"
    return None


def _is_wordy(text: str) -> bool:
    """Whether most of a line is letters — a heading, not a row of numbers."""
    dense = [char for char in text if not char.isspace()]
    if not dense:
        return False
    return sum(char.isalpha() for char in dense) / len(dense) > 0.5


def _level(text: str) -> int:
    """Nesting depth: '3 Model' is 1, '3.1 Encoder' is 2."""
    match = _NUMBERED.match(text.strip())
    if match is None:
        return 1
    return match.group(1).count(".") + 1


def section_id_at(sections: list[Section], offset: int) -> int | None:
    """The id of the section containing ``offset``, or ``None`` if unsectioned.

    Assumes ``sections`` is the ascending, contiguous list ``detect_sections``
    returns; called once per sentence, so it binary-searches rather than scans.
    """
    index = bisect_right([s.start_char for s in sections], offset) - 1
    if index < 0:
        return None
    section = sections[index]
    return section.id if offset < section.end_char else None
