"""Embeddings + term statistics.

Two complementary signals, both local and free:

* **feature-hashing vector** — word tokens and character n-grams folded into a
  fixed 384-dim space. Character n-grams are what make Arabic work: they
  tolerate affixes, diacritics and spelling drift without a stemmer.
* **term frequencies** — used for BM25-style lexical ranking.

If a provider embedding is configured later, only `embed()` needs to change;
`search.py` consumes vectors opaquely.
"""

from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

VECTOR_DIM = 384
_TOKEN = re.compile(r"[A-Za-z\u0600-\u06FF0-9]{2,}")
_DIACRITICS = re.compile(r"[ً-ْٰ]")


def normalise(text: str) -> str:
    text = _DIACRITICS.sub("", text or "")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    return text.lower()


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(normalise(text))


def _hash(token: str) -> tuple[int, int]:
    import zlib

    digest = zlib.crc32(token.encode("utf-8"))
    index = digest % VECTOR_DIM
    sign = 1.0 if (digest >> 16) & 1 else -1.0
    return index, sign


def embed(text: str) -> list[float]:
    """Deterministic, normalised feature-hashing embedding."""
    vec = np.zeros(VECTOR_DIM, dtype=np.float32)
    words = tokens(text)
    if not words:
        return vec.tolist()

    for word in words:
        index, sign = _hash("w:" + word)
        vec[index] += sign * 1.6
        # character 3-grams: the Arabic workhorse
        padded = f"^{word}$"
        for i in range(len(padded) - 2):
            gram = padded[i : i + 3]
            index, sign = _hash("c:" + gram)
            vec[index] += sign * 0.55
        if len(word) > 6:
            for i in range(len(word) - 4):
                index, sign = _hash("b:" + word[i : i + 5])
                vec[index] += sign * 0.3

    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    return [embed(t) for t in texts]


def cosine(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    if va.shape != vb.shape or not va.any() or not vb.any():
        return 0.0
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def term_frequencies(text: str) -> dict[str, int]:
    counts = Counter(tokens(text))
    return dict(counts.most_common(400))


def bm25_score(query: str, doc_terms: dict[str, int], doc_len: int, avg_len: float, idf: dict[str, float]) -> float:
    """Standard BM25 (k1=1.5, b=0.75) over pre-computed term frequencies."""
    if not doc_terms or doc_len <= 0:
        return 0.0
    k1, b = 1.5, 0.75
    score = 0.0
    for term in tokens(query):
        tf = doc_terms.get(term)
        if not tf:
            continue
        term_idf = idf.get(term, 1.0)
        denom = tf + k1 * (1 - b + b * doc_len / max(avg_len, 1.0))
        score += term_idf * (tf * (k1 + 1)) / max(denom, 1e-6)
    return score


def inverse_document_frequency(documents: list[dict[str, int]]) -> dict[str, float]:
    """IDF over the retrieved corpus; cheap because it runs per query."""
    n = max(len(documents), 1)
    df: Counter[str] = Counter()
    for doc in documents:
        df.update(doc.keys())
    return {term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}


__all__ = [
    "VECTOR_DIM",
    "embed",
    "embed_batch",
    "cosine",
    "tokens",
    "normalise",
    "term_frequencies",
    "bm25_score",
    "inverse_document_frequency",
]
