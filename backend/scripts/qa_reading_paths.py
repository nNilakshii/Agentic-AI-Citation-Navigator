"""Rank every sample paper for every goal and check the results (task 1.10).

This is the Phase 1 quality gate. It exercises the real pipeline — parse, rank,
cache — against all of ``data/samples`` and reports the things that would make a
reading path untrustworthy rather than merely imperfect:

- a span that does not cut its own text out of the document (offset drift)
- an id the model invented
- a path that silently lost a batch
- an empty or near-empty path, which looks identical to "nothing matched"
- goals that select the same sentences, which would mean the conditioning is
  doing no work

Free-tier Gemini allows 5 requests/minute, so this paces itself and is slow by
design. Results are cached, so a second run is nearly free.

Usage (backend/, venv active, server NOT required):

    python scripts/qa_reading_paths.py
    python scripts/qa_reading_paths.py --papers attention-is-all-you-need.pdf
    python scripts/qa_reading_paths.py --force      # ignore cached paths
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache import PaperStore  # noqa: E402
from app.core.pdf_parser import PARSER_VERSION, paper_id_for, parse_pdf  # noqa: E402
from app.core.reading_path import RANKER_VERSION, build_reading_path  # noqa: E402
from app.llm.client import GeminiClient, LLMError  # noqa: E402
from app.models.reading import ReadingGoal  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"

#: Spacing between live calls. The limit is 5/min; 13s leaves headroom for the
#: retry path without making a full run unbearable.
PACE_SECONDS = 13.0


def jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--papers", nargs="*", help="Sample filenames; default all")
    parser.add_argument("--force", action="store_true", help="Ignore cached paths")
    args = parser.parse_args()

    # A full sweep is ~30 calls against a 5/min quota. Run it while someone is
    # using the reader and *their* ranking queues behind it — measured at 62s
    # for one upload, which is indistinguishable from the app being broken.
    uncached = args.force or True
    if uncached and not args.papers:
        print(
            "Note: a full sweep consumes the shared Gemini quota for several "
            "minutes.\n"
            "      Don't run it while using the reader — interactive rankings "
            "will queue behind it.\n"
        )

    names = args.papers or sorted(p.name for p in SAMPLES.glob("*.pdf"))
    if not names:
        print(f"No PDFs in {SAMPLES}. Run scripts/fetch_sample_papers.py first.")
        return 1

    store = PaperStore()
    client = GeminiClient()
    problems: list[str] = []
    rows: list[dict] = []

    for name in names:
        path = SAMPLES / name
        if not path.is_file():
            problems.append(f"{name}: not found")
            continue

        pdf_bytes = path.read_bytes()
        paper_id = paper_id_for(pdf_bytes)
        paper = store.load_parsed(paper_id, PARSER_VERSION)
        if paper is None:
            paper = parse_pdf(pdf_bytes, name)
            store.save_pdf(paper_id, pdf_bytes)
            store.save_parsed(paper)

        selected: dict[str, set] = {}
        for goal in ReadingGoal:
            cached = (
                None
                if args.force
                else store.load_reading_path(
                    paper_id, PARSER_VERSION, goal, RANKER_VERSION
                )
            )
            if cached is not None:
                result = cached
                live = False
            else:
                try:
                    result = await build_reading_path(paper, goal, client)
                except LLMError as exc:
                    problems.append(f"{name} [{goal.value}]: ranking failed — {exc}")
                    continue
                live = True
                if result.is_complete:
                    store.save_reading_path(result)

            # --- the checks ---
            label = f"{name} [{goal.value}]"
            by_id = {s.id: s for s in paper.sentences}
            drifted = [
                i
                for i in result.items
                if paper.full_text[i.start_char : i.end_char] != i.text
            ]
            ghosts = [i for i in result.items if i.sentence_id not in by_id]
            if drifted:
                problems.append(
                    f"{label}: {len(drifted)} span(s) do not match the text"
                )
            if ghosts:
                problems.append(f"{label}: {len(ghosts)} unknown sentence id(s)")
            if result.n_hallucinated_ids:
                problems.append(
                    f"{label}: model returned {result.n_hallucinated_ids} invented id(s)"
                )
            if result.n_batches_failed:
                problems.append(
                    f"{label}: {result.n_batches_failed}/{result.n_batches} batches lost"
                )
            if not result.items:
                problems.append(f"{label}: empty path")
            missing_plain = [i for i in result.items if not i.plain]
            if missing_plain:
                problems.append(
                    f"{label}: {len(missing_plain)} item(s) with no explanation"
                )

            selected[goal.value] = {i.sentence_id for i in result.items}
            pages = sorted({i.page + 1 for i in result.items})
            rows.append(
                {
                    "paper": name.removesuffix(".pdf"),
                    "goal": goal.value,
                    "selected": len(result.items),
                    "considered": result.n_sentences_considered,
                    "pages": f"{len(pages)}/{paper.source.page_count}",
                    "first_page": pages[0] if pages else "-",
                }
            )
            if live:
                await asyncio.sleep(PACE_SECONDS)

        # Goals that pick the same sentences mean the conditioning is inert.
        if len(selected) == 3:
            overlaps = {
                f"{a}/{b}": jaccard(selected[a], selected[b])
                for a, b in (
                    ("skim", "in-depth"),
                    ("skim", "critique"),
                    ("in-depth", "critique"),
                )
            }
            worst = max(overlaps.values())
            if worst > 0.6:
                problems.append(
                    f"{name}: goals barely differ (max Jaccard {worst:.2f}) — "
                    "the goal conditioning may not be doing any work"
                )

    # --- report ---
    print(f"\n{'paper':26} {'goal':10} {'sel':>4} {'of':>5} {'pages':>7} {'1st':>4}")
    print("-" * 62)
    for r in rows:
        print(
            f"{r['paper'][:25]:26} {r['goal']:10} {r['selected']:>4} "
            f"{r['considered']:>5} {r['pages']:>7} {str(r['first_page']):>4}"
        )

    print(f"\n{len(rows)} rankings over {len(names)} papers.")
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nNo problems found.")
    return 0


if __name__ == "__main__":
    start = time.time()
    code = asyncio.run(main())
    print(f"({time.time() - start:.0f}s)")
    raise SystemExit(code)
