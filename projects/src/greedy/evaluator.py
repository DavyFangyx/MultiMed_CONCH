"""Evaluator protocol used by the greedy scheduler.

The scheduler owns nested CV (section 4.2). `evaluate(subset_idx)` is a single
train/val score for whatever split the evaluator was bound to. Clinic_Analyzer
is not required; inject any object with this method, or use StubEvaluator.
"""

from __future__ import annotations

from typing import Any, Protocol


class EvaluatorLike(Protocol):
    fields: list[str]

    def evaluate(self, subset_idx: list[int]) -> dict:
        """Return at least {"c_index_mean": float}."""


def extract_c_index(result: dict) -> tuple[float, float]:
    if result is None:
        raise ValueError("evaluator.evaluate returned None")
    if "c_index_mean" in result:
        mean = float(result["c_index_mean"])
    elif "c_index" in result:
        mean = float(result["c_index"])
    else:
        raise KeyError("evaluate() must return c_index_mean or c_index")
    std = float(result.get("c_index_std", 0.0) or 0.0)
    return mean, std


class CachedEvaluator:
    """Memoize subset scores by field set, independent of input order."""

    def __init__(self, inner: Any):
        self.inner = inner
        self.fields = list(getattr(inner, "fields", []))
        self._cache: dict[frozenset[int], dict] = {}
        self.n_calls = 0
        self.n_hits = 0

    def evaluate(self, subset_idx) -> dict:
        idx = [int(i) for i in list(subset_idx)]
        key = frozenset(idx)
        self.n_calls += 1
        cached = self._cache.get(key)
        if cached is not None:
            self.n_hits += 1
            return cached
        result = self.inner.evaluate(sorted(idx))
        self._cache[key] = result
        return result


class StubEvaluator:
    """Deterministic additive scorer for scheduler tests and --evaluator stub."""

    def __init__(self, fields: list[str], weights=None, split=None, noise: float = 0.0):
        self.fields = list(fields)
        n = len(self.fields)
        if weights is None:
            self.weights = [0.04 - 0.002 * i for i in range(n)]
        else:
            self.weights = [float(w) for w in weights]
            if len(self.weights) != n:
                raise ValueError("weights must match fields")
        self.split = split
        self.noise = float(noise)

    def evaluate(self, subset_idx) -> dict:
        idx = sorted({int(i) for i in list(subset_idx)})
        raw = sum(self.weights[i] for i in idx)
        # Diminishing returns so later steps shrink, matching a real curve.
        score = 0.5 + raw / (1.0 + 0.15 * max(len(idx) - 1, 0))
        if self.noise and self.split is not None:
            score += self.noise * _fold_jitter(self.split)
        return {
            "c_index_mean": float(score),
            "c_index_std": 0.0,
            "per_fold": [float(score)],
            "n_params": 0,
            "empty_rate": 0.0,
            "subset_idx": idx,
        }


def _fold_jitter(split) -> float:
    repeat = int(getattr(split, "repeat", 0) or 0)
    fold = int(getattr(split, "fold", 0) or 0)
    return ((repeat * 17 + fold * 13) % 11) / 11.0 - 0.5
