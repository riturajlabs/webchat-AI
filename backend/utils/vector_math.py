"""Shared math helpers for vector operations.

Both ``MongoVectorRepository`` (brute-force cosine fallback) and
``EmbeddingReranker`` implement an identical cosine-similarity function.
This module is the single source of truth so the two implementations cannot
drift (BE-Q14). Each caller keeps a thin module-local wrapper that delegates
here so existing references (and tests that monkeypatch them) are preserved.
"""

from __future__ import annotations

from math import sqrt


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors (0.0 on zero norm).

    Returns 0.0 when the vectors differ in length, are empty, or either has
    zero norm (matching the previous per-module behaviour exactly).
    """
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (sqrt(norm_a) * sqrt(norm_b))


__all__ = ["cosine_similarity"]
