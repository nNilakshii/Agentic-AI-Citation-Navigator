"""Check citation detection on every sample paper (task 2.1).

No ground-truth labels exist for these papers, so the gate rests on three
checks that do not need any, and that together catch both kinds of error:

- **links** — the share of detected citations that reach a reference entry.
  High is necessary but not sufficient: a parser that finds one reference and
  one citation scores 100% (this happened to two papers during development).
- **coverage** — the share of references cited at least once. Reference lists
  only hold works the paper cites, so an uncited entry is either a missed
  citation or a broken entry. This is what exposes missing citations.
- **consistency** — every link must agree with its entry: the printed number
  equals the label, or the cited surname and year appear in the entry.

Exits non-zero if any paper falls below the thresholds or any link disagrees.
Pure text processing: no network, no quota, about a second for all ten.

    python scripts/qa_citations.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import PaperStore  # noqa: E402
from app.core.citations import _normalise, build_citation_map  # noqa: E402
from app.core.pdf_parser import PARSER_VERSION, parse_pdf  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"

MIN_LINKED = 0.85
MIN_COVERAGE = 0.90


def consistent(style: str, anchor_text: str, ref) -> bool:
    if style == "numeric":
        numbers = set()
        for m in re.finditer(r"(\d+)(?:\s*[–-]\s*(\d+))?", anchor_text):
            lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
            numbers |= set(range(lo, hi + 1))
        return ref.label is not None and int(ref.label) in numbers
    return (
        ref.first_author is not None
        and _normalise(ref.first_author) in _normalise(anchor_text)
        and ref.year is not None
        and ref.year[:4] in anchor_text
    )


def main() -> int:
    store = PaperStore()
    problems: list[str] = []
    totals = [0, 0, 0, 0]  # linked, anchors, cited, references

    print(f"{'paper':26} {'style':12} {'refs':>4} {'cited':>9} {'linked':>11}")
    for pdf in sorted(SAMPLES.glob("*.pdf")):
        data = pdf.read_bytes()
        paper = store.load_parsed(hashlib.sha256(data).hexdigest(), PARSER_VERSION)
        if paper is None:
            paper = parse_pdf(data, pdf.name)
        m = build_citation_map(paper)

        refs = {r.id: r for r in m.references}
        linked = [a for a in m.anchors if a.reference_id]
        cited = {a.reference_id for a in linked}
        link_rate = len(linked) / len(m.anchors) if m.anchors else 0.0
        coverage = len(cited) / len(m.references) if m.references else 0.0
        totals[0] += len(linked)
        totals[1] += len(m.anchors)
        totals[2] += len(cited)
        totals[3] += len(m.references)

        print(
            f"{pdf.stem[:25]:26} {m.style.value:12} {len(m.references):>4} "
            f"{len(cited):>4} {coverage:4.0%} {len(linked):>4}/{len(m.anchors):<4}"
            f"{link_rate:4.0%}"
        )

        label = pdf.stem
        if not m.references:
            problems.append(f"{label}: no reference list found")
            continue
        if link_rate < MIN_LINKED:
            problems.append(f"{label}: only {link_rate:.0%} of citations linked")
        if coverage < MIN_COVERAGE:
            problems.append(f"{label}: only {coverage:.0%} of references cited")
        for a in linked:
            if not consistent(m.style.value, a.text, refs[a.reference_id]):
                problems.append(
                    f"{label}: {a.text!r} linked to {a.reference_id}, which disagrees"
                )
        unlinked = [a.text for a in m.anchors if not a.reference_id]
        uncited = [r.first_author or r.label for r in m.references if r.id not in cited]
        if unlinked:
            print(f"{'':26} unlinked: {unlinked}")
        if uncited:
            print(f"{'':26} uncited:  {uncited}")

    linked, anchors, cited, references = totals
    print(
        f"\n{linked}/{anchors} citations linked ({linked / max(anchors, 1):.1%}); "
        f"{cited}/{references} references cited ({cited / max(references, 1):.1%})."
    )
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("No problems found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
