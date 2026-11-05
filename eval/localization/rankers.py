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

import re
import threading

import numpy as np

from app.core.embedding import CACHE_DIR, SentenceTransformerEmbedder, encode_cached

# BM25 and the hybrid live in the backend, so what is evaluated is what is served.
from app.core.lexical import bm25_scores, hybrid_scores  # noqa: F401

SPECTER2 = "allenai/specter2_base+allenai/specter2"


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
