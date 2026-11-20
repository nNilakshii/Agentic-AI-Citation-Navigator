"""Citation-intent classification on SciCite: macro-F1 (task 3.2).

Scores ``app/core/intent.py`` on SciCite as released (3.1). The labels are
imbalanced (test: 54% background, 33% method, 14% result), so the headline is
**macro-F1** — the published numbers (Cohan et al. 2019: 84.0; SciBERT 85.5)
are macro-F1 on all 1,861 test rows, and so is ours.

A reply that is not one of the three labels counts as *invalid*: wrong for
its gold class, and a false positive for none. A failed call is reported and
makes the run INCOMPLETE; it is never scored as a label.

Prompt development uses a fixed stratified sample of dev (``--sample``);
test is run once, with the setting chosen there.

    python eval/intent/run_scicite_eval.py --split dev --sample 200
    python eval/intent/run_scicite_eval.py --split dev --sample 200 --no-section
    python eval/intent/run_scicite_eval.py --split test --save
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "backend")]

from scicite import LABELS, load, sample  # noqa: E402

RESULTS = HERE / "results"
CACHE = ROOT / "data" / "raw" / "intent-cache"
PREDICTIONS = ROOT / "data" / "raw" / "intent-predictions"


def evaluate(predictions: list[dict], gold: list[dict]) -> dict:
    """predictions / gold: [{"citance_id": str, "intent": str | None}, ...]

    Returns accuracy, macro-F1, per-class P/R/F1 and the confusion matrix.
    Every gold id must have a prediction; ``None`` is an invalid reply.
    """
    predicted = {p["citance_id"]: p["intent"] for p in predictions}
    missing = [g["citance_id"] for g in gold if g["citance_id"] not in predicted]
    if missing:
        raise ValueError(f"{len(missing)} gold ids have no prediction")
    pairs = [(g["intent"], predicted[g["citance_id"]]) for g in gold]
    n = len(pairs)
    per_class = {}
    for label in LABELS:
        tp = sum(1 for g, p in pairs if g == label and p == label)
        fp = sum(1 for g, p in pairs if g != label and p == label)
        fn = sum(1 for g, p in pairs if g == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": tp + fn,
        }
    confusion = Counter((g, p or "invalid") for g, p in pairs)
    return {
        "n": n,
        "accuracy": sum(g == p for g, p in pairs) / n if n else 0.0,
        "macro_f1": sum(c["f1"] for c in per_class.values()) / len(LABELS),
        "per_class": per_class,
        "invalid": sum(p is None for _, p in pairs),
        "confusion": {
            g: {p: confusion[(g, p)] for p in (*LABELS, "invalid")} for g in LABELS
        },
    }


def classify_all(examples, llm, use_section: bool, concurrency: int, version: str):
    from app.core.intent import classify
    from app.llm.client import LLMError

    async def one(example, gate):
        async with gate:
            try:
                r = await classify(
                    example.text,
                    llm,
                    section=example.section if use_section else None,
                    cache_dir=CACHE,
                    version=version,
                )
            except LLMError as exc:
                print(f"  ! {example.id}: {exc}"[:200])
                return None
            return r

    async def all_of():
        gate = asyncio.Semaphore(concurrency)
        return await asyncio.gather(*(one(e, gate) for e in examples))

    return asyncio.run(all_of())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--sample", type=int, help="dev only: stratified sample of N")
    parser.add_argument(
        "--no-section", action="store_true", help="classify from the text alone"
    )
    parser.add_argument(
        "--prompt-version", help="app/core/intent.py DEFINITIONS key (default: current)"
    )
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--save", action="store_true", help="Write results/*.json")
    args = parser.parse_args()
    if args.sample and args.split == "test":
        parser.error("test is scored whole: --sample is for prompt development")
    if args.sample and args.save:
        parser.error("--save is for full splits; a sample's numbers are not results")

    from app.config import get_settings
    from app.core.intent import CONFIDENCE, DEFINITIONS, INTENT_VERSION

    version = args.prompt_version or INTENT_VERSION
    if version not in DEFINITIONS:
        parser.error(f"unknown prompt version {version!r}: {sorted(DEFINITIONS)}")
    from app.llm.client import GeminiClient

    examples = load(args.split)
    if args.sample:
        examples = sample(examples, args.sample)
    llm = GeminiClient()
    started = time.monotonic()
    results = classify_all(
        examples, llm, not args.no_section, args.concurrency, version
    )
    elapsed = time.monotonic() - started

    failed = [e for e, r in zip(examples, results) if r is None]
    scored = [(e, r) for e, r in zip(examples, results) if r is not None]
    report = evaluate(
        [{"citance_id": e.id, "intent": r.intent} for e, r in scored],
        [{"citance_id": e.id, "intent": e.label} for e, _ in scored],
    )
    by_confidence = {}
    for c in CONFIDENCE:
        group = [(e, r) for e, r in scored if r.confidence == c]
        by_confidence[c] = {
            "n": len(group),
            "accuracy": (
                sum(e.label == r.intent for e, r in group) / len(group)
                if group
                else None
            ),
        }
    thinking = get_settings().llm_thinking_budget
    summary = {
        "split": args.split,
        "sample": args.sample,
        "rows": len(examples),
        "failed_calls": len(failed),
        "model": llm.model,
        "thinking_budget": thinking,
        "intent_version": version,
        "uses_section": not args.no_section,
        **report,
        "by_confidence": by_confidence,
        "from_cache": sum(r.cached for _, r in scored),
    }

    where = f"{args.split}" + (f" (sample {args.sample})" if args.sample else "")
    print(
        f"SciCite intent — {llm.model}"
        + (f", thinking {thinking}" if thinking else "")
        + (", text only" if args.no_section else ", text + section")
        + f", prompt v{version} — {where}"
    )
    print(
        f"  {report['n']} scored, {len(failed)} failed calls, "
        f"{summary['from_cache']} from cache, {elapsed:.0f}s"
    )
    print(
        f"  macro-F1 {report['macro_f1']:.3f}  accuracy {report['accuracy']:.1%}  "
        f"invalid {report['invalid']}"
    )
    for label, c in report["per_class"].items():
        print(
            f"    {label:10} P {c['precision']:.2f}  R {c['recall']:.2f}  "
            f"F1 {c['f1']:.2f}  (n={c['support']})"
        )
    print("  confusion (rows gold, columns predicted):")
    for g, row in report["confusion"].items():
        print(f"    {g:10} " + "  ".join(f"{p[:4]} {v:4}" for p, v in row.items()))
    print(
        "  accuracy by confidence: "
        + ", ".join(
            f"{c} {v['accuracy']:.0%} (n={v['n']})"
            for c, v in by_confidence.items()
            if v["n"]
        )
    )
    if failed:
        print("  INCOMPLETE: re-run to fill the failed calls (replies are cached)")

    if args.save:
        RESULTS.mkdir(exist_ok=True)
        tag = (
            f"llm-{llm.model}"
            + (f"-think{thinking}" if thinking else "")
            + ("-text-only" if args.no_section else "")
            + f"-v{version}-{args.split}"
        )
        (RESULTS / f"{tag}.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"  saved eval/intent/results/{tag}.json")
        # Per-example rows carry SciCite text: kept under data/raw/ (gitignored).
        PREDICTIONS.mkdir(parents=True, exist_ok=True)
        with (PREDICTIONS / f"{tag}.jsonl").open("w") as out:
            for e, r in zip(examples, results):
                out.write(
                    json.dumps(
                        {
                            "id": e.id,
                            "gold": e.label,
                            "predicted": r.intent if r else None,
                            "confidence": r.confidence if r else None,
                            "failed": r is None,
                        }
                    )
                    + "\n"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
