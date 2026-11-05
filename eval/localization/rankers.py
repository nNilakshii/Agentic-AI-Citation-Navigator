"""Rankers compared in the baseline evaluation (task 2.7).

Every ranker maps (passages, queries) to a score matrix, one row per query;
the harness then applies the app's own overlap suppression (``select_top``),
so rankers differ only in how they score.

- ``embedding``: any sentence-transformers model, as the app runs it (2.5).
- ``specter2``: SPECTER2 with its proximity adapter, the scientific-text model
  the literature review recommended. Needs the ``adapters`` package (dev only).
- ``bm25``: Okapi BM25 over each paper's own passages — the lexical method
  much of CL-SciSumm was built on, and the bar an embedding model must clear.
- ``hybrid``: BM25 and embedding scores, each z-normalised per query, mixed
  with weight ``alpha`` on the embedding side.
"""

from __future__ import annotations

import math
import re
import threading
from collections import Counter

import numpy as np

from app.core.embedding import CACHE_DIR, SentenceTransformerEmbedder, encode_cached

SPECTER2 = "allenai/specter2_base+allenai/specter2"
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an the of in on to for with by from as at and or is are was were be been "
    "this that these those it its we our their which can such".split()
)


class Specter2Embedder:
    """SPECTER2 base + proximity adapter; [CLS] vectors, unit length."""

    model = SPECTER2

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded = None

    def encode(self, texts: list[str]) -> np.ndarray:
        import torch

        with self._lock:
            if self._loaded is None:
                from adapters import AutoAdapterModel
                from transformers import AutoTokenizer

                tokenizer = AutoTokenizer.from_pretrained("allenai/specter2_base")
                model = AutoAdapterModel.from_pretrained("allenai/specter2_base")
                model.load_adapter(
                    "allenai/specter2",
                    source="hf",
                    load_as="proximity",
                    set_active=True,
                )
                device = "mps" if torch.backends.mps.is_available() else "cpu"
                self._loaded = (tokenizer, model.to(device).eval(), device)
            tokenizer, model, device = self._loaded
            out = []
            for i in range(0, len(texts), 32):
                batch = tokenizer(
                    texts[i : i + 32],
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt",
                    return_token_type_ids=False,
                ).to(device)
                with torch.no_grad():
                    cls = model(**batch).last_hidden_state[:, 0, :]
                out.append(torch.nn.functional.normalize(cls, dim=-1).cpu().numpy())
        return np.concatenate(out).astype(np.float32)


def make_embedder(model: str):
    return (
        Specter2Embedder() if model == SPECTER2 else SentenceTransformerEmbedder(model)
    )


def embedding_scores(embedder, passages: list[str], queries: list[str]) -> np.ndarray:
    vectors = encode_cached(embedder, passages, CACHE_DIR)
    return encode_cached(embedder, queries, CACHE_DIR) @ vectors.T


def bm25_scores(
    passages: list[str], queries: list[str], k1: float = 1.5, b: float = 0.75
) -> np.ndarray:
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


def hybrid_scores(lexical: np.ndarray, dense: np.ndarray, alpha: float) -> np.ndarray:
    return alpha * _z(dense) + (1 - alpha) * _z(lexical)


def _z(scores: np.ndarray) -> np.ndarray:
    mean = scores.mean(axis=1, keepdims=True)
    std = scores.std(axis=1, keepdims=True)
    return (scores - mean) / np.where(std == 0, 1, std)


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]
