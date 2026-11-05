"""Lexical scoring for the localizer: BM25 and its mix with embeddings (2.7).

On CL-SciSumm's dev split, BM25 alone beat MiniLM (sentence F1 0.152 vs
0.130): citing sentences often reuse the cited paper's own terms, which exact
matching rewards and an embedding blurs. Mixing the two beat both (0.182), and
held on test (0.166 vs 0.146 and 0.112). See ``docs/architecture.md``.

BM25 is fitted per query over one paper's passages, so its statistics describe
that paper, and it needs no index or dependency.
"""

from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

#: Weight on the embedding side of the mix, chosen on the dev split.
HYBRID_ALPHA = 0.7

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an the of in on to for with by from as at and or is are was were be been "
    "this that these those it its we our their which can such".split()
)


def bm25_scores(
    passages: list[str], queries: list[str], k1: float = 1.5, b: float = 0.75
) -> np.ndarray:
    """Okapi BM25, one row per query, one column per passage."""
    docs = [_tokens(p) for p in passages]
    n = len(docs)
    avg = sum(map(len, docs)) / max(n, 1)
    df = Counter(t for d in docs for t in set(d))
    idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
    tfs = [Counter(d) for d in docs]
    out = np.zeros((len(queries), n), dtype=np.float32)
    for qi, query in enumerate(queries):
        terms = set(_tokens(query))
        for di, (tf, doc) in enumerate(zip(tfs, docs)):
            norm = k1 * (1 - b + b * len(doc) / avg) if avg else k1
            out[qi, di] = sum(
                idf[t] * tf[t] * (k1 + 1) / (tf[t] + norm) for t in terms if t in tf
            )
    return out


def hybrid_scores(
    lexical: np.ndarray, dense: np.ndarray, alpha: float = HYBRID_ALPHA
) -> np.ndarray:
    """Each side z-normalised per query, then mixed: the scales differ wildly."""
    return alpha * _z(dense) + (1 - alpha) * _z(lexical)


def _z(scores: np.ndarray) -> np.ndarray:
    mean = scores.mean(axis=1, keepdims=True)
    std = scores.std(axis=1, keepdims=True)
    return (scores - mean) / np.where(std == 0, 1, std)


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]
