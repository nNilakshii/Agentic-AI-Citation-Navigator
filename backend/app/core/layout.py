"""Walk a PDF's span stream, building ``full_text`` and its offset↔bbox map.

The load-bearing rule from ``docs/architecture.md``:

    Build ``full_text`` by walking the span stream and appending separators
    explicitly, recording each span's ``(start_char, end_char)`` as it is
    appended. The offsets are a byproduct of construction, never a lookup after
    the fact.

The tempting alternative — take ``page.get_text()`` as the text and ``str.find()``
each span to locate it — drifts silently, because ``get_text()`` inserts line and
block separators the span stream does not contain (measured: 1827 vs 1800 chars
on one page of the Transformer paper). Plausible-but-wrong offsets misalign every
highlight downstream, so we never let them exist.
"""

from dataclasses import dataclass, field

import pymupdf

#: Separator between text blocks. Also the paragraph delimiter the sentence
#: segmenter splits on, so it must be exactly two newlines.
BLOCK_SEPARATOR = "\n\n"

#: Separator between wrapped lines inside one block. A space, not a newline:
#: within a block the line break is a typesetting artifact, not a semantic one.
LINE_SEPARATOR = " "

_TEXT_BLOCK = 0  # pymupdf block["type"] for text; 1 is an image


@dataclass
class LaidOutSpan:
    """One PyMuPDF span, with the offsets it occupies in ``full_text``."""

    start: int
    end: int
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    font: str

    @property
    def n_chars(self) -> int:
        return self.end - self.start


@dataclass
class LaidOutLine:
    """One rendered line. Carries the font evidence that heading detection uses."""

    start: int
    end: int
    page: int
    text: str
    size: float
    bold: bool


@dataclass
class LayoutText:
    """The document as one string, plus the geometry behind every character."""

    full_text: str
    spans: list[LaidOutSpan] = field(default_factory=list)
    lines: list[LaidOutLine] = field(default_factory=list)


class _TextBuilder:
    """Accumulates text while recording where each span landed.

    Kept as a class because de-hyphenation has to reach back and shorten the
    previous span, which is only safe if one object owns both the buffer and the
    span records.
    """

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._cursor = 0
        self.spans: list[LaidOutSpan] = []

    @property
    def cursor(self) -> int:
        return self._cursor

    def append_separator(self, sep: str) -> None:
        if not self._parts:
            return  # never open the document with whitespace
        self._parts.append(sep)
        self._cursor += len(sep)

    def append_span(self, text: str, span: dict, page: int) -> None:
        """Append a span's text and record the offsets it occupies."""
        if not text:
            return
        start = self._cursor
        self._parts.append(text)
        self._cursor += len(text)
        x0, y0, x1, y1 = span["bbox"]
        self.spans.append(
            LaidOutSpan(
                start=start,
                end=self._cursor,
                page=page,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                size=round(float(span.get("size", 0.0)), 2),
                font=str(span.get("font", "")),
            )
        )

    def ends_with_soft_hyphen(self) -> bool:
        """True if the buffer ends in a hyphen that a letter precedes."""
        tail = self.tail(2)
        return len(tail) == 2 and tail[1] == "-" and tail[0].isalpha()

    def drop_last_char(self) -> None:
        """Remove the final character, shrinking the span that contributed it.

        Used to join a word broken across lines. The span record must shrink with
        the buffer or every later offset in that span would be off by one.
        """
        if not self._parts:
            return
        last = self._parts[-1]
        if not last:
            return
        self._parts[-1] = last[:-1]
        self._cursor -= 1
        if self.spans and self.spans[-1].end == self._cursor + 1:
            self.spans[-1].end -= 1
            if self.spans[-1].n_chars == 0:
                self.spans.pop()

    def tail(self, n: int) -> str:
        """The last ``n`` characters of the buffer so far."""
        out = ""
        for part in reversed(self._parts):
            out = part + out
            if len(out) >= n:
                break
        return out[-n:]

    def text(self) -> str:
        return "".join(self._parts)


def extract_layout(doc: pymupdf.Document) -> LayoutText:
    """Extract ``full_text`` plus per-span and per-line geometry from ``doc``.

    Blocks are consumed in PyMuPDF's native order, which is the PDF's own content
    order. That is the correct reading order for LaTeX-produced papers, including
    two-column ones; geometric sorting would zig-zag between columns instead.
    """
    builder = _TextBuilder()
    lines: list[LaidOutLine] = []

    for page_number, page in enumerate(doc):
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != _TEXT_BLOCK:
                continue
            first_line_of_block = True
            for line in block.get("lines", []):
                spans = _usable_spans(line)
                if not spans:
                    continue
                line_start, line_text = _append_line(
                    builder, spans, page_number, first_line_of_block
                )
                first_line_of_block = False
                lines.append(
                    LaidOutLine(
                        start=line_start,
                        end=builder.cursor,
                        page=page_number,
                        text=line_text,
                        size=max(round(float(s.get("size", 0.0)), 2) for s in spans),
                        bold=any(_is_bold(s) for s in spans),
                    )
                )

    return LayoutText(full_text=builder.text(), spans=builder.spans, lines=lines)


def _usable_spans(line: dict) -> list[dict]:
    """The spans of a line, trimmed at the edges, dropping blank-only lines."""
    spans = [dict(s) for s in line.get("spans", []) if s.get("text")]
    if not spans or not any(s["text"].strip() for s in spans):
        return []
    # Trim edge whitespace *before* appending, so offsets never need fixing up.
    spans[0]["text"] = spans[0]["text"].lstrip()
    spans[-1]["text"] = spans[-1]["text"].rstrip()
    return [s for s in spans if s["text"]]


def _append_line(
    builder: _TextBuilder, spans: list[dict], page: int, starts_block: bool
) -> tuple[int, str]:
    """Append one line's spans, choosing the separator that precedes it."""
    if starts_block:
        builder.append_separator(BLOCK_SEPARATOR)
    elif builder.ends_with_soft_hyphen() and spans[0]["text"][:1].islower():
        builder.drop_last_char()  # "represen-" + "tation" -> "representation"
    else:
        builder.append_separator(LINE_SEPARATOR)

    line_start = builder.cursor
    for span in spans:
        builder.append_span(span["text"], span, page)
    return line_start, "".join(s["text"] for s in spans)


def _is_bold(span: dict) -> bool:
    """PyMuPDF exposes weight both as a flag bit and in the font name."""
    if span.get("flags", 0) & 2**4:  # bit 4 = bold
        return True
    return "bold" in str(span.get("font", "")).lower()
