"""Task 1A metrics for cited-span localization (2.6).

- **Sentence-overlap P/R/F1**, as the official 2018 script computes it: true
  positives, false positives and false negatives are counted over sentence
  ids, pooled across every citance of one reference paper; P/R/F1 per paper;
  then averaged over papers. Also reported pooled over all citances.
- **ROUGE-L F1** between predicted and gold text. This is a plain LCS
  implementation over lowercased word tokens, not the official ROUGE-1.5.5
  Perl script — comparable within this project, approximate against papers.
- **Accuracy@k**: the share of citances where any of the top-k passages
  shares at least one sentence with the gold span. The UI shows a ranked
  list, so this is the number closest to what a reader experiences.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def add(self, predicted: set[str], gold: set[str]) -> None:
        self.tp += len(predicted & gold)
        self.fp += len(predicted - gold)
        self.fn += len(gold - predicted)

    def prf(self) -> tuple[float, float, float]:
        p = self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0
        r = self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        return p, r, f


def averaged_over_papers(per_paper: Iterable[Counts]) -> tuple[float, float, float]:
    """Official-style: P/R/F1 per paper, then the mean of each."""
    scores = [c.prf() for c in per_paper]
    if not scores:
        return 0.0, 0.0, 0.0
    return tuple(sum(s[i] for s in scores) / len(scores) for i in range(3))


def hit_at_k(ranked: list[set[str]], gold: set[str], k: int) -> bool:
    return any(sentences & gold for sentences in ranked[:k])


def rouge_l(predicted: str, gold: str) -> float:
    """ROUGE-L F1 (beta = 1) over lowercased word tokens."""
    a, b = _TOKEN.findall(predicted.lower()), _TOKEN.findall(gold.lower())
    if not a or not b:
        return 0.0
    lcs = _lcs(a, b)
    if lcs == 0:
        return 0.0
    p, r = lcs / len(a), lcs / len(b)
    return 2 * p * r / (p + r)


def _lcs(a: list[str], b: list[str]) -> int:
    previous = [0] * (len(b) + 1)
    for x in a:
        current = [0]
        for j, y in enumerate(b):
            current.append(
                previous[j] + 1 if x == y else max(previous[j + 1], current[j])
            )
        previous = current
    return previous[-1]
