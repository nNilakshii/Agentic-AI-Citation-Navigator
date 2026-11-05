"""Check cited-paper fetching on the sample papers (task 2.3).

For the first ``--limit`` references of each sample paper, walks the fallback
ladder for real and reports how often it ends at full text, abstract only, or
unavailable — and why each PDF attempt failed, grouped, so the common causes
are visible at a glance.

Fetched papers go to their own store under ``data/fetch-qa/`` (gitignored),
never the committed ``data/cache/parsed/``: these are third-party papers and
must not be published with the repo. A second run reuses them and is fast; a
cold run is paced by arXiv's one-request-per-three-seconds rule.

    python scripts/qa_fetch.py                       # 5 references per paper
    python scripts/qa_fetch.py --limit 20 --papers attention-is-all-you-need
"""

from __future__ import annotations

import argparse
import hashlib
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import PaperStore  # noqa: E402
from app.core.cited_text import fetch_cited_text  # noqa: E402
from app.core.citations import build_citation_map  # noqa: E402
from app.core.pdf_parser import PARSER_VERSION, parse_pdf  # noqa: E402
from app.core.resolution import resolve_references  # noqa: E402
from app.models.cited import TextSource  # noqa: E402
from app.scholar.client import SemanticScholar  # noqa: E402
from app.scholar.download import Downloader  # noqa: E402
from app.scholar.openalex import OpenAlex  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples"
QA_STORE = ROOT / "data" / "fetch-qa"
MIN_TEXT = 0.85  # full text or abstract, among resolved references


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5, help="References per paper")
    parser.add_argument("--papers", nargs="*", help="Sample file stems to include")
    args = parser.parse_args()

    samples, qa_store = PaperStore(), PaperStore(QA_STORE)
    scholar, downloader, openalex = SemanticScholar(), Downloader(), OpenAlex()
    outcomes: Counter[TextSource] = Counter()
    reasons: Counter[str] = Counter()
    abstracts_from: Counter[str] = Counter()
    sentences: list[int] = []
    unavailable: list[str] = []
    resolved_n = resolved_with_text = 0
    started = time.monotonic()

    print(f"{'paper':26} {'tried':>5} {'full':>5} {'abs':>5} {'none':>5}")
    for pdf in sorted(SAMPLES.glob("*.pdf")):
        if args.papers and pdf.stem not in args.papers:
            continue
        data = pdf.read_bytes()
        paper = samples.load_parsed(hashlib.sha256(data).hexdigest(), PARSER_VERSION)
        if paper is None:
            paper = parse_pdf(data, pdf.name)
        resolution = resolve_references(paper, build_citation_map(paper), scholar)

        row: Counter[TextSource] = Counter()
        for item in resolution.items[: args.limit]:
            result = fetch_cited_text(
                paper,
                item.reference_id,
                resolution,
                qa_store,
                scholar,
                downloader,
                openalex,
            )
            row[result.source] += 1
            reasons.update(_reason(a) for a in result.attempts)
            if result.source is TextSource.FULL_TEXT:
                sentences.append(result.n_sentences)
            if result.abstract_from:
                abstracts_from[result.abstract_from] += 1
            if item.resolved:
                resolved_n += 1
                resolved_with_text += result.source is not TextSource.UNAVAILABLE
                if result.source is TextSource.UNAVAILABLE:
                    unavailable.append(f"{pdf.stem[:14]:15} {item.title!r:.70}")
        outcomes.update(row)
        print(
            f"{pdf.stem[:25]:26} {sum(row.values()):>5} "
            f"{row[TextSource.FULL_TEXT]:>5} {row[TextSource.ABSTRACT]:>5} "
            f"{row[TextSource.UNAVAILABLE]:>5}"
        )

    tried = sum(outcomes.values())
    print(
        f"\n{tried} references: "
        + ", ".join(
            f"{outcomes[s]} {s.value} ({outcomes[s] / max(tried, 1):.0%})"
            for s in TextSource
        )
        + f". {time.monotonic() - started:.0f}s."
    )
    if sentences:
        print(
            f"Full-text parses: median {statistics.median(sentences):.0f} sentences, "
            f"smallest {min(sentences)}."
        )
    if abstracts_from:
        print(
            "Abstracts from: "
            + ", ".join(f"{k} {v}" for k, v in abstracts_from.most_common())
        )
    if reasons:
        print("\nWhy PDF or abstract attempts failed:")
        for reason, n in reasons.most_common():
            print(f"  {n:>3}  {reason}")
    if unavailable:
        print("\nResolved, but no text at all:")
        print("\n".join(f"  {line}" for line in unavailable))

    rate = resolved_with_text / max(resolved_n, 1)
    print(f"\nResolved references with some text: {rate:.1%} (need {MIN_TEXT:.0%}).")
    return 0 if rate >= MIN_TEXT else 1


def _reason(attempt: str) -> str:
    """Group attempts by cause: drop the URL and anything specific to it."""
    reason = re.sub(r"^https?://\S+: ", "", attempt)
    host = re.match(r"^https?://([^/]+)/", attempt)
    reason = re.sub(r"\(.*\)$", "(...)", reason)
    return f"{reason}  [{host.group(1)}]" if host else reason


if __name__ == "__main__":
    raise SystemExit(main())
