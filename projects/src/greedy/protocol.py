"""5-fold greedy scheduler.

One shared 5-fold split is used for inner search and outer reporting.
Each candidate embedding is evaluated once on a model with all 5 folds.
Greedy decisions use the 5-fold val c-index; reported scores use test.
"""

from __future__ import annotations

from copy import deepcopy

from .evaluator import CachedEvaluator, extract_c_index
from .search import greedy_forward
from .splits import FoldSplit
from .stability import selection_frequency
from .stopping import apply_stopping_rules


def _bind_evaluator(factory, split: FoldSplit, *, seed: int, for_test: bool):
    if factory is None:
        raise ValueError("evaluator_factory is required")
    try:
        return factory(split, seed=seed, for_test=for_test)
    except TypeError:
        return factory(split)


def _bind_shared_evaluator(factory, splits: list[FoldSplit], *, seed: int, for_test: bool):
    if factory is None:
        raise ValueError("evaluator_factory is required")
    try:
        return factory(splits, seed=seed, for_test=for_test)
    except TypeError:
        return _bind_evaluator(factory, splits[0] if splits else None, seed=seed, for_test=for_test)


def _test_metrics(result: dict) -> tuple[float, float, list[float]]:
    if result is None:
        raise ValueError("evaluator.evaluate returned None")
    if "test_c_index_mean" in result:
        mean = float(result["test_c_index_mean"])
        std = float(result.get("test_c_index_std", 0.0) or 0.0)
        per_fold = [float(x) for x in (result.get("test_per_fold") or [])]
        return mean, std, per_fold
    mean, std = extract_c_index(result)
    per_fold = [float(x) for x in (result.get("per_fold") or [mean])]
    return mean, std, per_fold


def _fold_records_from_shared_path(path: list[dict], prefix_results: list[dict], splits: list[FoldSplit]) -> list[dict]:
    n_folds = max(len(splits), 1)
    per_step_folds = []
    for result in prefix_results:
        _, _, per_fold = _test_metrics(result)
        if not per_fold:
            mean, _, _ = _test_metrics(result)
            per_fold = [mean] * n_folds
        if len(per_fold) < n_folds:
            per_fold = list(per_fold) + [per_fold[-1]] * (n_folds - len(per_fold))
        per_step_folds.append(per_fold[:n_folds])

    records = []
    for i, split in enumerate(splits or [None]):
        test_scores = [row[i] for row in per_step_folds]
        records.append(
            {
                "fold_id": getattr(split, "fold_id", f"f{i}"),
                "repeat": getattr(split, "repeat", 0),
                "fold": getattr(split, "fold", i),
                "n_train": len(getattr(split, "train", []) or []),
                "n_val": len(getattr(split, "val", []) or []),
                "n_test": len(getattr(split, "test", []) or []),
                "path": path,
                "test_scores": test_scores,
                "test_details": [{"c_index": score, "k": step["step"]} for step, score in zip(path, test_scores)],
            }
        )
    return records


def run_nested_greedy(
    evaluator_factory,
    splits: list[FoldSplit],
    candidate_idx=None,
    fields: list[str] | None = None,
    max_steps=None,
    patience: int = 3,
    seed: int = 0,
):

    evaluator = _bind_shared_evaluator(evaluator_factory, splits, seed=seed, for_test=False)
    if fields is None:
        fields = list(getattr(evaluator, "fields", []))
    cached = CachedEvaluator(evaluator)
    path = greedy_forward(
        cached,
        candidate_idx=candidate_idx,
        max_steps=max_steps,
        patience=patience,
    )

    empty_result = cached.evaluate([])
    empty_score, empty_std, _ = _test_metrics(empty_result)
    prefix_results = []
    test_details = []
    test_scores = []
    for step in path:
        result = cached.evaluate(step["subset_idx"])
        score, std, _ = _test_metrics(result)
        prefix_results.append(result)
        test_scores.append(score)
        test_details.append({"c_index": score, "c_index_std": std, "k": step["step"]})

    fold_records = _fold_records_from_shared_path(path, prefix_results, splits)
    for rec in fold_records:
        rec["empty_test_score"] = empty_score
        rec["empty_test_std"] = empty_std
        rec["inner_calls"] = cached.n_calls
        rec["inner_cache_hits"] = cached.n_hits
        rec["outer_calls"] = cached.n_calls
        rec["outer_cache_hits"] = cached.n_hits
        rec["test_details"] = rec.get("test_details") or test_details

    stopping = apply_stopping_rules(fold_records, patience=patience)
    freq = selection_frequency([path], fields=fields)
    return {
        "fields": list(fields or []),
        "n_folds": len(fold_records),
        "fold_records": fold_records,
        "stopping": stopping,
        "selection_freq": freq,
        "points": deepcopy(stopping["points"]),
        "path": path,
        "test_scores": test_scores,
        "test_details": test_details,
    }
