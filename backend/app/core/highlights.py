"""Turn a character span into the rectangles a renderer draws a highlight over.

This is the bridge between the two coordinate systems in ``docs/architecture.md``:
character offsets are what the NLP works in, bounding boxes are what the PDF
renderer needs. Every span-producing feature — the reading path (1.7), cited-span
localization (2.12), grounded chat citations (3.4) — highlights through here.
"""

from bisect import bisect_left

from app.core.layout import LaidOutSpan
from app.models.paper import BBox

#: Vertical tolerance, in PDF points, for treating two rects as the same line.
_SAME_LINE_TOLERANCE = 2.0

#: Horizontal gap, in points, wider than which two rects stay separate — a
#: column break rather than a word space.
_MAX_MERGE_GAP = 12.0


def bboxes_for_span(
    spans: list[LaidOutSpan], span_starts: list[int], start: int, end: int
) -> list[BBox]:
    """The rectangles covering characters ``[start, end)``.

    Args:
        spans: All laid-out spans, ascending by ``start``.
        span_starts: ``[s.start for s in spans]``, precomputed for binary search.
        start: First character offset covered.
        end: One past the last character offset covered.

    Returns:
        One rectangle per rendered line, merged left to right. A span only
        partially covered is clipped horizontally in proportion to the characters
        selected, so a highlight that begins mid-line begins at the right x.
    """
    rects: list[BBox] = []
    for span in _overlapping(spans, span_starts, start, end):
        rects.append(_clip(span, start, end))
    return _merge_adjacent(rects)


def _overlapping(
    spans: list[LaidOutSpan], span_starts: list[int], start: int, end: int
):
    """Yield the spans intersecting ``[start, end)``, in document order."""
    index = max(0, bisect_left(span_starts, start) - 1)
    for span in spans[index:]:
        if span.start >= end:
            break
        if span.end > start and span.n_chars > 0:
            yield span


def _clip(span: LaidOutSpan, start: int, end: int) -> BBox:
    """Narrow a span's rectangle to the selected characters.

    Assumes uniform character width within the span, which is wrong for
    proportional fonts but only ever applies to the first and last span of a
    selection — an error of a few points at the edge of a highlight.
    """
    width = span.x1 - span.x0
    first = max(0, start - span.start) / span.n_chars
    last = min(span.n_chars, end - span.start) / span.n_chars
    return BBox(
        page=span.page,
        x0=span.x0 + width * first,
        y0=span.y0,
        x1=span.x0 + width * last,
        y1=span.y1,
    )


def _merge_adjacent(rects: list[BBox]) -> list[BBox]:
    """Union rectangles that sit on the same line and touch."""
    merged: list[BBox] = []
    for rect in rects:
        previous = merged[-1] if merged else None
        if previous is not None and _same_line(previous, rect):
            previous.x0 = min(previous.x0, rect.x0)
            previous.x1 = max(previous.x1, rect.x1)
            previous.y0 = min(previous.y0, rect.y0)
            previous.y1 = max(previous.y1, rect.y1)
        else:
            merged.append(rect.model_copy())
    return merged


def _same_line(a: BBox, b: BBox) -> bool:
    if a.page != b.page:
        return False
    if abs(a.y0 - b.y0) > _SAME_LINE_TOLERANCE:
        return False
    return b.x0 - a.x1 <= _MAX_MERGE_GAP
