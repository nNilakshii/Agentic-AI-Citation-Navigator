"""Check reference resolution on every sample paper (task 2.2).

Reports, per paper, how many references were identified and how many have a
PDF that 2.3 can fetch, then lists every match that was not an exact title
match (for a human to eyeball — one wrong match was found this way) and every
entry left unresolved.

Responses are cached under data/cache/s2/, so after the first run this makes
no network calls and takes about a second. A cold run is bounded by Semantic
Scholar's rate limit, which in practice is much tighter than its advertised one
request per second.

    python scripts/qa_resolution.py
    python scripts/qa_resolution.py --title-search   # slow: one request per miss
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import PaperStore  # noqa: E402
from app.core.citations import build_citation_map  # noqa: E402
from app.core.pdf_parser import PARSER_VERSION, parse_pdf  # noqa: E402
from app.core.resolution import resolve_references  # noqa: E402
from app.scholar.client import SemanticScholar  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"
MIN_RESOLVED = 0.90  # across all papers; individual ones vary with their field


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title-search", action="store_true")
    args = parser.parse_args()

    store, scholar = PaperStore(), SemanticScholar()
    problems: list[str] = []
    inexact: list[str] = []
    missed: list[str] = []
    total = resolved_total = pdf_total = 0

    print(f"{'paper':26} {'refs':>4} {'resolved':>10} {'pdf':>10}")
    for pdf in sorted(SAMPLES.glob("*.pdf")):
        data = pdf.read_bytes()
        paper = store.load_parsed(hashlib.sha256(data).hexdigest(), PARSER_VERSION)
        if paper is None:
            paper = parse_pdf(data, pdf.name)
        citations = build_citation_map(paper)
        result = resolve_references(
            paper, citations, scholar, title_search=args.title_search
        )
        entries = {r.id: r for r in citations.references}

        n = len(result.items)
        done = sum(item.resolved for item in result.items)
        pdfs = sum(bool(item.pdf_url) for item in result.items)
        total, resolved_total, pdf_total = (
            total + n,
            resolved_total + done,
            pdf_total + pdfs,
        )
        flag = "" if result.complete else "  INCOMPLETE"
        print(
            f"{pdf.stem[:25]:26} {n:>4} {done:>4} {done / max(n, 1):5.0%} {pdfs:>4} {pdfs / max(n, 1):5.0%}{flag}"
        )

        if not result.complete:
            problems.append(
                f"{pdf.stem}: a request failed; some entries were never tried"
            )
        for item in result.items:
            entry = entries[item.reference_id].text
            if item.resolved and item.confidence < 1.0:
                inexact.append(
                    f"[{item.confidence:.2f}] {item.title!r:.60}  <-  {entry[:60]!r}"
                )
            if not item.resolved:
                missed.append(f"{pdf.stem[:14]:15} {entry[:80]!r}")

    rate = resolved_total / max(total, 1)
    print(
        f"\n{resolved_total}/{total} references resolved ({rate:.1%}); "
        f"{pdf_total}/{total} with a fetchable PDF ({pdf_total / max(total, 1):.1%}). "
        f"{scholar.network_calls} network call(s)."
    )
    if inexact:
        print(f"\nInexact matches to check by eye ({len(inexact)}):")
        for line in inexact:
            print(f"  {line}")
    if missed:
        print(f"\nUnresolved ({len(missed)}):")
        for line in missed:
            print(f"  {line}")
    if rate < MIN_RESOLVED:
        problems.append(f"only {rate:.1%} resolved overall (want {MIN_RESOLVED:.0%})")

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nNo problems found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
