"""Where should the app say "not sure"? (task 2.7)

Reads per-citance predictions written by ``run_clscisumm_eval.py --save`` and,
for a range of thresholds on the top passage's score, reports how many
citances clear it and how accurate the ones that clear it are. A threshold is
picked on dev and only *checked* on test.

    python eval/localization/analyze_confidence.py embedding-all-MiniLM-L6-v2
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PREDICTIONS = (
    Path(__file__).resolve().parents[2] / "data" / "raw" / "clscisumm-predictions"
)


def load(tag: str, split: str) -> list[dict]:
    path = PREDICTIONS / f"{tag}-{split}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def curve(
    rows: list[dict], thresholds: list[float]
) -> list[tuple[float, float, float, float]]:
    """(threshold, share answered, acc@1 when answered, acc@3 when answered)."""
    out = []
    for t in thresholds:
        kept = [r for r in rows if r["top"] and r["top"][0]["score"] >= t]
        if not kept:
            out.append((t, 0.0, 0.0, 0.0))
            continue
        acc1 = sum(r["hit_at_1"] for r in kept) / len(kept)
        acc3 = sum(
            any(set(p["sentences"]) & set(r["gold"]) for p in r["top"][:3])
            for r in kept
        ) / len(kept)
        out.append((t, len(kept) / len(rows), acc1, acc3))
    return out


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else "embedding-all-MiniLM-L6-v2"
    for split in ("dev", "test"):
        try:
            rows = load(tag, split)
        except FileNotFoundError:
            print(f"no predictions for {tag}-{split}; run the harness with --save")
            continue
        scores = sorted(r["top"][0]["score"] for r in rows if r["top"])
        quantiles = [
            scores[int(q * (len(scores) - 1))] for q in (0, 0.25, 0.5, 0.75, 0.9)
        ]
        print(f"\n{tag} — {split} ({len(rows)} citances)")
        print(
            "  top-score quantiles 0/25/50/75/90%: "
            + " ".join(f"{q:.3f}" for q in quantiles)
        )
        print("  threshold  answered  acc@1  acc@3")
        for t, share, a1, a3 in curve(
            rows, [round(quantiles[0] + i * 0.05, 2) for i in range(12)]
        ):
            print(f"    {t:6.2f}    {share:6.0%}  {a1:6.1%} {a3:6.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
