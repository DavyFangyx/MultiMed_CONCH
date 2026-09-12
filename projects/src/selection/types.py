from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


class BudgetExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class EvalResult:
    subset: tuple[str, ...]
    subset_idx: tuple[int, ...]
    k: int
    cv_c_mean: float | None
    cv_folds: tuple[float, ...]
    logical_eval_idx: int
    physical_cache_hit: bool
    wall_ms: int
    status: Literal["ok", "error"]
    error: str | None = None


@dataclass(frozen=True)
class SearchResult:
    algorithm: str
    seed: int
    best_subset: tuple[str, ...]
    best_cv_c_mean: float
    recommended_subset: tuple[str, ...]
    stop_reason: str
    logical_evals: int
    physical_trains: int
    proposal_count: int
    metadata: dict = field(default_factory=dict)
