"""SciCite: citation intents, loaded and audited (task 3.1).

Cohan et al., NAACL 2019. 11,020 citation contexts labelled background /
method / result, from AllenAI's official release
(``s3://ai2-s2-research/scicite/scicite.tar.gz``, sha256 711ece2c…3af499193),
unpacked to ``data/raw/scicite/`` (gitignored):

    mkdir -p data/raw/scicite && cd data/raw/scicite
    curl -O https://s3-us-west-2.amazonaws.com/ai2-s2-research/scicite/scicite.tar.gz
    tar -xzf scicite.tar.gz scicite/train.jsonl scicite/dev.jsonl scicite/test.jsonl

What the audit found, and what follows from it:

- **The citation offsets are unreliable.** About 10% point at the wrong text
  ("he " for "[40]", "Atlantic", a span cut mid-bracket) and 6 are NaN. The
  classifier therefore reads the citation text exactly as given — which is
  also what the SciCite baseline was scored on — and never text cut at them.
- **No test text appears in train**, so nothing leaks into the benchmark.
  14 dev texts also occur in train: harmless for scoring, but dev is for
  prompt development only and its numbers are not reported as results.
- **A few duplicates** (train 41, test 4), and three texts carry two labels.
  Splits load **as released** by default — published SciCite scores are on
  all 1,861 test rows, and a comparison is only fair on the same rows.
  ``dedupe=True`` drops exact repeats (first kept), for prompt development.
- **Section names are sometimes NaN** (a float, not text); read as "none".
- **Imbalanced labels** (test: 54% background, 33% method, 14% result), which
  is why the benchmark is scored by macro-F1, not accuracy.
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "raw" / "scicite" / "scicite"
LABELS = ("background", "method", "result")
SPLITS = ("train", "dev", "test")


@dataclass(frozen=True)
class Example:
    id: str
    text: str
    label: str
    section: str
    citing_paper_id: str
    cited_paper_id: str


def load(split: str, data: Path = DATA, dedupe: bool = False) -> list[Example]:
    """One split as released (or with exact repeats dropped), labels checked."""
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}")
    examples: list[Example] = []
    seen: set[str] = set()
    for line in (data / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        text = (row.get("string") or "").strip()
        label = row.get("label")
        if not text or label not in LABELS:
            continue
        key = _norm(text)
        if dedupe and key in seen:
            continue
        seen.add(key)
        examples.append(
            Example(
                id=row.get("unique_id") or row.get("id") or f"{split}-{len(examples)}",
                text=text,
                label=label,
                section=_text(row.get("sectionName")),
                citing_paper_id=row.get("citingPaperId", ""),
                cited_paper_id=row.get("citedPaperId", ""),
            )
        )
    return examples


def sample(examples: list[Example], n: int, seed: int = 0) -> list[Example]:
    """``n`` examples stratified by label, for prompt development on dev.

    Small and fixed, so iterating on a prompt costs a known handful of calls.
    """
    by_label: dict[str, list[Example]] = defaultdict(list)
    for example in examples:
        by_label[example.label].append(example)
    rng = random.Random(seed)
    picked: list[Example] = []
    total = len(examples)
    for label in LABELS:
        pool = by_label[label]
        k = max(1, round(n * len(pool) / total)) if pool else 0
        picked.extend(rng.sample(pool, min(k, len(pool))))
    rng.shuffle(picked)
    return picked[:n]


def audit(data: Path = DATA) -> dict:
    """The facts the module docstring states, recomputed from the files."""
    raw = {
        s: [
            json.loads(l)
            for l in (data / f"{s}.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        for s in SPLITS
    }
    report: dict = {"splits": {}}
    texts = {}
    for split, rows in raw.items():
        labels = Counter(r.get("label") for r in rows)
        bad_offsets = 0
        for r in rows:
            span = _span(r)
            if span is None or not any(ch.isdigit() for ch in span):
                bad_offsets += 1
        norm = Counter(_norm(r.get("string") or "") for r in rows)
        label_sets = defaultdict(set)
        for r in rows:
            label_sets[_norm(r.get("string") or "")].add(r.get("label"))
        texts[split] = set(norm)
        report["splits"][split] = {
            "rows": len(rows),
            "loaded": len(load(split, data)),
            "unique": len(load(split, data, dedupe=True)),
            "labels": dict(labels),
            "duplicate_texts": sum(v - 1 for v in norm.values() if v > 1),
            "conflicting_labels": sum(1 for v in label_sets.values() if len(v) > 1),
            "suspect_offsets": bad_offsets,
        }
    report["overlap"] = {
        "train_test": len(texts["train"] & texts["test"]),
        "train_dev": len(texts["train"] & texts["dev"]),
        "dev_test": len(texts["dev"] & texts["test"]),
    }
    return report


def _span(row: dict) -> str | None:
    try:
        start, end = int(float(row["citeStart"])), int(float(row["citeEnd"]))
    except (KeyError, TypeError, ValueError):
        return None
    return row.get("string", "")[start:end]


def _text(value) -> str:
    """A string field that the release sometimes stores as NaN."""
    return value.strip() if isinstance(value, str) else ""


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
