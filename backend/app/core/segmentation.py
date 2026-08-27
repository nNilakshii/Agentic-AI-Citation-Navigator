"""Abbreviation-aware sentence segmentation that returns character offsets.

Decision (1.1): hand-rolled rather than pysbd/spaCy. The requirement here is
unusual — we need *offsets into the exact string we built*, not a list of
sentence texts. A library that normalises whitespace or re-tokenises would break
the offset contract that the whole architecture rests on, and scientific prose
needs a custom abbreviation list anyway ("et al.", "Fig. 3", "0.05", "J. Doe").
No new dependency, and the failure modes are ours to fix.

The only public entry point is :func:`split_sentences`.
"""

import re

#: Tokens that end in a period but do not end a sentence. Matched case-folded
#: against the whitespace-delimited token immediately preceding the period.
ABBREVIATIONS: frozenset[str] = frozenset(
    {
        # citation / cross-reference
        "al.",
        "cf.",
        "e.g.",
        "i.e.",
        "viz.",
        "etc.",
        "vs.",
        "resp.",
        "ibid.",
        # document parts
        "fig.",
        "figs.",
        "eq.",
        "eqs.",
        "sec.",
        "secs.",
        "tab.",
        "tabs.",
        "ref.",
        "refs.",
        "app.",
        "ch.",
        "chap.",
        "no.",
        "nos.",
        "pp.",
        "p.",
        "vol.",
        "ed.",
        "eds.",
        # titles
        "dr.",
        "prof.",
        "mr.",
        "mrs.",
        "ms.",
        "st.",
        # measurement / hedging
        "approx.",
        "avg.",
        "est.",
        "min.",
        "max.",
        "inc.",
        "ltd.",
        "dept.",
        "univ.",
        "u.s.",
        "u.k.",
    }
)

#: Upper bound on a single span, in characters. Comfortably above any real
#: sentence; below the point where an extracted table would blow up an embedding
#: model's input window.
MAX_SENTENCE_CHARS = 1000

#: A run of terminal punctuation, optional closing quotes/brackets, then space.
_BOUNDARY = re.compile(r"([.!?]+)([\"'\)\]\}]*)(\s+)")

#: Paragraph break — the parser emits "\n\n" between blocks, and a block break
#: is always a sentence break regardless of punctuation (headings, list items).
_PARAGRAPH = re.compile(r"\n\s*\n")

#: What a real sentence may start with.
_STARTS_SENTENCE = re.compile(r"[A-Z0-9\"'\(\[‘“]")

#: A single capital letter with a period — an initial, as in "J. Doe".
_INITIAL = re.compile(r"^[A-Z]\.$")

#: Trailing token before the boundary punctuation, e.g. "al" in "et al."
_LAST_TOKEN = re.compile(r"(\S+)\s*$")


def split_sentences(
    text: str, *, min_chars: int = 2, max_chars: int = MAX_SENTENCE_CHARS
) -> list[tuple[int, int]]:
    """Split ``text`` into sentences, as ``(start_char, end_char)`` offsets.

    Offsets index into ``text`` unchanged, so ``text[start:end]`` is the
    sentence. Leading and trailing whitespace is excluded from every span, and
    spans never overlap.

    Args:
        text: The document's ``full_text``.
        min_chars: Spans with fewer non-whitespace characters are dropped —
            page furniture, stray punctuation from figures.
        max_chars: Longer spans are hard-split at whitespace. Measured on the
            sample papers this fires on 0.05% of spans, all of them extracted
            table bodies with no terminal punctuation anywhere. Splitting them
            does not make them prose; it bounds what the embedder (1.6) and the
            LLM prompts downstream have to accept.

    Returns:
        Ascending, non-overlapping offset pairs.
    """
    spans: list[tuple[int, int]] = []
    for para_start, para_end in _paragraphs(text):
        for start, end in _split_paragraph(text, para_start, para_end):
            spans.extend(_enforce_max_length(text, start, end, max_chars))
    return [(s, e) for s, e in spans if len(text[s:e].strip()) >= min_chars]


def _enforce_max_length(
    text: str, start: int, end: int, max_chars: int
) -> list[tuple[int, int]]:
    """Break an over-long span at the last whitespace before the limit."""
    if end - start <= max_chars:
        return [(start, end)]

    pieces: list[tuple[int, int]] = []
    while end - start > max_chars:
        limit = start + max_chars
        cut = text.rfind(" ", start, limit)
        if cut <= start:
            cut = limit  # a single unbroken run; split it anyway
        pieces.append(_strip(text, start, cut))
        start = cut
    pieces.append(_strip(text, start, end))
    return pieces


def _paragraphs(text: str) -> list[tuple[int, int]]:
    """Offsets of the paragraph blocks, split on blank lines."""
    blocks: list[tuple[int, int]] = []
    cursor = 0
    for match in _PARAGRAPH.finditer(text):
        blocks.append((cursor, match.start()))
        cursor = match.end()
    blocks.append((cursor, len(text)))
    return [b for b in blocks if b[0] < b[1]]


def _split_paragraph(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split one paragraph on genuine sentence boundaries."""
    spans: list[tuple[int, int]] = []
    cursor = start
    for match in _BOUNDARY.finditer(text, start, end):
        if not _is_boundary(text, match, end):
            continue
        # The sentence keeps its punctuation and closing quotes, not the space.
        spans.append((cursor, match.end(2)))
        cursor = match.end()
    if cursor < end:
        spans.append((cursor, end))
    return [_strip(text, s, e) for s, e in spans if s < e]


def _is_boundary(text: str, match: re.Match[str], para_end: int) -> bool:
    """Decide whether a punctuation-then-space match really ends a sentence."""
    # What follows must be able to start a sentence. A paragraph's final
    # punctuation always ends it, whatever comes after the block break.
    after = match.end()
    if after >= para_end:
        return True
    if not _STARTS_SENTENCE.match(text, after):
        return False

    # "!" and "?" are unambiguous; only "." carries the abbreviation problem.
    if match.group(1) != ".":
        return True

    # A bounded look-back: the longest abbreviation we track is far shorter than
    # this, and scanning from 0 would make segmentation quadratic in doc length.
    token_match = _LAST_TOKEN.search(text, max(0, match.start() - 40), match.start())
    if token_match is None:
        return True
    token = token_match.group(1) + "."
    if _INITIAL.match(token):
        return False
    return token.lower() not in ABBREVIATIONS


def _strip(text: str, start: int, end: int) -> tuple[int, int]:
    """Shrink a span past leading and trailing whitespace."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end
