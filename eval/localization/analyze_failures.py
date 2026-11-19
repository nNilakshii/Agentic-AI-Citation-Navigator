"""Why the localizer misses: a failure taxonomy over CL-SciSumm (task 2.10).

Reads the per-citance predictions written by ``run_clscisumm_eval.py --save``
and puts every miss (top passage shares no sentence with the gold) in exactly
one bucket, checked in this order:

1. **unreachable** — no gold sentence survived 2.4's candidate exclusions, so
   no ranker could find it. Fixable only in passage segmentation.
2. **adjacent** — the top passage ends within ``NEAR`` sentences of the gold: the
   right place, the wrong window. Mostly a boundary problem, cheap to fix.
3. **ranked-lower** — the gold is in the top 5, just not first. A re-ranker
   (2.8's LLM, 2.9's cross-encoder) works on exactly these.
4. **same-section** — the top passage is in the gold's section but further away.
5. **elsewhere** — a different part of the paper altogether.

Beside the bucket, three attributes that say *why*, computed the same way for
every citance (hits too, so each can be compared with the base rate):

- **lexical support** — the share of the citance's content words that appear
  in the gold text. Low support means the citing author paraphrased or cited
  vaguely, and word matching has little to go on.
- **distractor** — whether the top passage shares more of those words than
  the gold does: the ranker followed the words, and the words pointed wrong.
- **gold size** — how many sentences the gold spans; more than 3 cannot fit one
  candidate window, so overlap F1 is capped.

The buckets are automatic; the hand-read sample (``--sample``) is what names
the reasons behind ``elsewhere`` (docs/build-log.md, 2.10).

    python eval/localization/analyze_failures.py hybrid-all-MiniLM-L6-v2-a0.7 --split dev
    python eval/localization/analyze_failures.py hybrid-all-MiniLM-L6-v2-a0.7 --split dev --sample 30
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "backend")]

from app.core.lexical import _tokens  # noqa: E402
from app.core.passages import passages_from_paper  # noqa: E402
from clscisumm import CORPUS, load_reference, papers, split_of  # noqa: E402

ROOT = HERE.parents[1]
PREDICTIONS = ROOT / "data" / "raw" / "clscisumm-predictions"
RESULTS = HERE / "results"
BUCKETS = ("unreachable", "adjacent", "ranked-lower", "same-section", "elsewhere")
NEAR = 2
LOW_SUPPORT = 0.2


@dataclass(frozen=True)
class Diagnosis:
    citance: str
    hit: bool
    bucket: str | None  # None for a hit
    support: float  # share of the citance's content words found in the gold
    distractor: bool  # top passage shares more of them than the gold does
    gold_size: int


def support(query: str, text: str) -> float:
    """Share of the query's distinct content words that occur in ``text``."""
    words = set(_tokens(query))
    if not words:
        return 0.0
    return len(words & set(_tokens(text))) / len(words)


def bucket_of(
    top: list[list[str]],
    gold: set[str],
    candidates: set[str],
    section_of: dict[str, int | None],
) -> str:
    """The first bucket a miss falls in (module docstring, 1-5)."""
    if not gold & candidates:
        return "unreachable"
    first = top[0] if top else []
    if first and _distance(first, gold) <= NEAR:
        return "adjacent"
    if any(set(p) & gold for p in top[:5]):
        return "ranked-lower"
    gold_sections = {section_of.get(g) for g in gold} - {None}
    if first and {section_of.get(s) for s in first} & gold_sections:
        return "same-section"
    return "elsewhere"


def diagnose(
    row: dict,
    text_of: dict[str, str],
    candidates: set[str],
    section_of: dict[str, int | None],
) -> Diagnosis:
    gold = set(row["gold"])
    top = [p["sentences"] for p in row["top"]]
    gold_text = " ".join(text_of.get(g, "") for g in sorted(gold, key=int))
    top_text = " ".join(text_of.get(s, "") for s in (top[0] if top else []))
    gold_support = support(row["query"], gold_text)
    return Diagnosis(
        citance=row["citance"],
        hit=bool(row["hit_at_1"]),
        bucket=(
            None if row["hit_at_1"] else bucket_of(top, gold, candidates, section_of)
        ),
        support=gold_support,
        distractor=support(row["query"], top_text) > gold_support,
        gold_size=len(gold),
    )


def summarize(diagnoses: list[Diagnosis]) -> dict:
    n = len(diagnoses)
    misses = [d for d in diagnoses if not d.hit]
    buckets = Counter(d.bucket for d in misses)

    def rate(group: list[Diagnosis]) -> dict:
        return {
            "n": len(group),
            "acc_at_1": sum(d.hit for d in group) / len(group) if group else None,
        }

    low = [d for d in diagnoses if d.support < LOW_SUPPORT]
    return {
        "citances": n,
        "misses": len(misses),
        "buckets": {
            b: {"n": buckets[b], "share_of_misses": buckets[b] / max(len(misses), 1)}
            for b in BUCKETS
        },
        "by_support": {
            f"< {LOW_SUPPORT}": rate(low),
            f">= {LOW_SUPPORT}": rate(
                [d for d in diagnoses if d.support >= LOW_SUPPORT]
            ),
        },
        "by_gold_size": {
            "1": rate([d for d in diagnoses if d.gold_size == 1]),
            "2-3": rate([d for d in diagnoses if 2 <= d.gold_size <= 3]),
            "4+": rate([d for d in diagnoses if d.gold_size >= 4]),
        },
        "misses_with_distractor": sum(d.distractor for d in misses)
        / max(len(misses), 1),
        "median_support": {
            "hits": _median([d.support for d in diagnoses if d.hit]),
            "misses": _median([d.support for d in misses]),
        },
    }


def _distance(sentences: list[str], gold: set[str]) -> int:
    return min(abs(int(s) - int(g)) for s in sentences for g in gold)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="e.g. hybrid-all-MiniLM-L6-v2-a0.7")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument(
        "--sample", type=int, default=0, help="misses to dump for reading"
    )
    parser.add_argument(
        "--save", action="store_true", help="Write results/failures-*.json"
    )
    args = parser.parse_args()

    path = PREDICTIONS / f"{args.tag}-{args.split}.jsonl"
    if not path.exists():
        print(f"no predictions at {path}; run the harness with --save")
        return 1
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    by_paper: dict[str, list[dict]] = {}
    for row in rows:
        by_paper.setdefault(row["citance"].split("#")[0], []).append(row)

    diagnoses, cases = [], []
    for paper in papers(CORPUS):
        if split_of(paper) != args.split or paper not in by_paper:
            continue
        reference = load_reference(paper)
        text_of = {s.id: s.text for s in reference.sentences}
        section_of = {s.id: s.section_id for s in reference.sentences}
        titles = {s.id: s.title for s in reference.sections}
        candidates = {
            i
            for p in passages_from_paper(reference).passages
            if len(p.sentence_ids) <= 3
            for i in p.sentence_ids
        }
        for row in by_paper[paper]:
            d = diagnose(row, text_of, candidates, section_of)
            diagnoses.append(d)
            if not d.hit:
                top = row["top"][0]["sentences"] if row["top"] else []
                cases.append(
                    {
                        "citance": d.citance,
                        "bucket": d.bucket,
                        "support": round(d.support, 2),
                        "query": row["query"],
                        "gold_section": titles.get(section_of.get(row["gold"][0])),
                        "gold": " ".join(text_of.get(g, "") for g in row["gold"]),
                        "top_section": (
                            titles.get(section_of.get(top[0])) if top else None
                        ),
                        "top": " ".join(text_of.get(s, "") for s in top),
                    }
                )

    summary = {"tag": args.tag, "split": args.split, **summarize(diagnoses)}
    print(f"Failure taxonomy — {args.tag} — {args.split}")
    print(f"  {summary['citances']} citances, {summary['misses']} misses at @1")
    for b, v in summary["buckets"].items():
        print(f"    {b:13} {v['n']:4}  {v['share_of_misses']:6.1%}")
    print(
        f"  misses where the top passage out-matches the gold on words: "
        f"{summary['misses_with_distractor']:.0%}"
    )
    print(
        f"  median lexical support: hits {summary['median_support']['hits']:.2f}, "
        f"misses {summary['median_support']['misses']:.2f}"
    )
    for name in ("by_support", "by_gold_size"):
        print(
            f"  acc@1 {name.replace('_', ' ')}: "
            + ", ".join(
                f"{k} {v['acc_at_1']:.0%} (n={v['n']})"
                for k, v in summary[name].items()
                if v["n"]
            )
        )

    if args.save:
        out = RESULTS / f"failures-{args.tag}-{args.split}.json"
        out.write_text(json.dumps(summary, indent=2) + "\n")
        print(f"  saved {out.relative_to(ROOT)}")
    if args.sample:
        # Corpus text: written under data/raw/ (gitignored), never results/.
        picked = random.Random(0).sample(cases, min(args.sample, len(cases)))
        out = PREDICTIONS / f"failure-sample-{args.tag}-{args.split}.json"
        out.write_text(json.dumps(picked, indent=2, ensure_ascii=False) + "\n")
        print(f"  {len(picked)} sampled misses: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
