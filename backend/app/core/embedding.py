"""Sentence embeddings for localization (task 2.5).

Behind a small protocol, like the LLM client, so tests use a fake and the
evaluation (2.7) can swap models: MiniLM is the fast default, Specter2 the
scientific-text candidate.

Two costs shape this module, both measured on the samples:

- **Importing sentence-transformers takes ~13s** (torch). It is imported on
  first use, never at app start, so the reader and every other endpoint stay
  fast.
- **Embedding a paper's ~1,000 passages takes ~5s** on a laptop GPU and longer
  on a server CPU, so passage embeddings are cached on disk, keyed by the model
  and the exact passage texts — any change to segmentation is a new key.
"""

from __future__ import annotations

import hashlib
import threading
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache" / "embeddings"
BATCH_SIZE = 64


class EmbedderUnavailable(RuntimeError):
    """sentence-transformers is not installed (the production image omits torch)."""


class Embedder(Protocol):
    model: str

    def encode(self, texts: list[str]) -> np.ndarray:
        """Unit-length vectors, one row per text."""
        ...


class SentenceTransformerEmbedder:
    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        self._loaded = None
        self._lock = threading.Lock()

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        with self._lock:
            if self._loaded is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError as exc:
                    raise EmbedderUnavailable(
                        "sentence-transformers is not installed on this deployment"
                    ) from exc

                self._loaded = SentenceTransformer(self.model)
            vectors = self._loaded.encode(
                texts, batch_size=BATCH_SIZE, normalize_embeddings=True
            )
        return np.asarray(vectors, dtype=np.float32)


def encode_cached(
    embedder: Embedder, texts: list[str], cache_dir: Path | None = CACHE_DIR
) -> np.ndarray:
    """``embedder.encode(texts)``, remembered on disk by model and texts."""
    if cache_dir is None or not texts:
        return embedder.encode(texts)
    digest = hashlib.sha256(
        "\x1e".join([embedder.model, *texts]).encode("utf-8")
    ).hexdigest()
    path = cache_dir / f"{digest}.npy"
    try:
        vectors = np.load(path)
        if vectors.shape[0] == len(texts):
            return vectors
    except (OSError, ValueError):
        pass
    vectors = embedder.encode(texts)
    cache_dir.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.stem + ".tmp.npy")
    np.save(temp, vectors)
    temp.replace(path)
    return vectors


@lru_cache
def get_embedder() -> Embedder:
    """Injectable factory — FastAPI overrides this in tests. One model per process."""
    return SentenceTransformerEmbedder()
