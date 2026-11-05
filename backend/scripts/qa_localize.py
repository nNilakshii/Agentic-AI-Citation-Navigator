"""Eyeball localizer v1 on real citations from the sample papers (task 2.5).

There is no ground truth here — that is CL-SciSumm's job (2.6, 2.7). This
prints, for a few citations per sample whose cited paper is already fetched,
the citing sentence and the top passages, for a human to judge; and it times
the first (cold) and later (cached) localizations.

Uses the QA store from ``qa_fetch.py`` (``data/fetch-qa/``), so run that
first; references it has not fetched are skipped, not fetched.

    python scripts/qa_localize.py --per-paper 2
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import PaperStore  # noqa: E402
from app.core.citations import build_citation_map  # noqa: E402
from app.core.embedding import SentenceTransformerEmbedder  # noqa: E402
from app.core.localizer import localize  # noqa: E402
from app.core.pdf_parser import PARSER_VERSION  # noqa: E402
from app.core.resolution import resolve_references  # noqa: E402
from app.models.cited import TextSource  # noqa: E402
from app.scholar.client import SemanticScholar  # noqa: E402
from app.scholar.download import DownloadError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples"
QA_STORE = ROOT / "data" / "fetch-qa"
QA_EMBEDDINGS = QA_STORE / "embeddings"


class OfflineDownloader:
    """Only what qa_fetch.py already stored; never the network."""

    def fetch_pdf(self, url: str) -> bytes:
        raise DownloadError("not fetched by qa_fetch.py")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-paper", type=int, default=2)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    samples, qa_store = PaperStore(), PaperStore(QA_STORE)
    scholar = SemanticScholar()
    embedder = (
        SentenceTransformerEmbedder(args.model)
        if args.model
        else SentenceTransformerEmbedder()
    )
    timings: list[float] = []

    for pdf in sorted(SAMPLES.glob("*.pdf")):
        data = pdf.read_bytes()
        paper = samples.load_parsed(hashlib.sha256(data).hexdigest(), PARSER_VERSION)
        citations = build_citation_map(paper)
        resolution = resolve_references(paper, citations, scholar)
        fetched = {
            i.reference_id
            for i in resolution.items
            if any(qa_store.load_fetched(u) for u in filter(None, [i.pdf_url]))
        }
        shown, seen_refs = 0, set()
        for anchor in citations.anchors:
            if shown == args.per_paper:
                break
            ref = anchor.reference_id
            if ref not in fetched or ref in seen_refs:
                continue
            seen_refs.add(ref)
            started = time.monotonic()
            result = localize(
                paper,
                anchor.id,
                resolution,
                qa_store,
                scholar,
                OfflineDownloader(),
                None,
                embedder,
                args.k,
                cache_dir=QA_EMBEDDINGS,
            )
            timings.append(time.monotonic() - started)
            if result.source is not TextSource.FULL_TEXT:
                continue
            shown += 1
            title = next(i.title for i in resolution.items if i.reference_id == ref)
            print(f"\n=== {pdf.stem} -> {title!r:.70}")
            print(f"    citing: {result.query[:220]!r}")
            for r in result.results:
                where = (r.passage.section_title or "")[:24]
                print(
                    f"    {r.rank}. [{r.score:.3f}] ({where}) {r.passage.text[:200]!r}"
                )

    if timings:
        print(
            f"\n{len(timings)} localizations; first {timings[0]:.1f}s (model load + "
            f"embedding), median {sorted(timings)[len(timings) // 2]:.2f}s."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
