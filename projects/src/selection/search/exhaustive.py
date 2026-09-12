from __future__ import annotations

import itertools
import math
import statistics
import time

from .base import Searcher, finish, score
from ..types import BudgetExhausted


ANCHOR_TIMING_DATASETS = ("TCGA-BRCA", "TCGA-LGG", "TCGA-CHOL")
ANCHOR_LANDMARKS = ("landmark_0", "landmark_365", "landmark_730", "landmark_none")


def choose_p_anchor(n_instances: int, t_median_seconds: float, workers: int, hours=30.0):
    if n_instances <= 0 or t_median_seconds <= 0 or workers <= 0:
        raise ValueError("n_instances, t_median_seconds, and workers must be positive")
    feasible = [
        p for p in range(8, 16)
        if n_instances * (2 ** p - 1) * t_median_seconds / workers <= float(hours) * 3600
    ]
    return max(feasible) if feasible else None


def stratified_anchor_datasets(patient_counts: dict[str, int]) -> tuple[str, ...]:
    """Take first/middle/last study from each patient-count tertile."""
    ordered = sorted(patient_counts, key=lambda name: (int(patient_counts[name]), name))
    if not ordered:
        return ()
    strata = [ordered[: len(ordered) // 3], ordered[len(ordered) // 3 : 2 * len(ordered) // 3], ordered[2 * len(ordered) // 3 :]]
    chosen = []
    for group in strata:
        if not group:
            continue
        for index in (0, len(group) // 2, len(group) - 1):
            if group[index] not in chosen:
                chosen.append(group[index])
    return tuple(chosen)


def build_anchor_plan(patient_counts, t_median_seconds, workers, hours=30.0) -> dict:
    datasets = tuple(sorted(patient_counts))
    landmarks = ANCHOR_LANDMARKS
    p_anchor = choose_p_anchor(len(datasets) * len(landmarks), t_median_seconds, workers, hours)
    stage = "all_instances"
    if p_anchor is None:
        datasets = stratified_anchor_datasets(patient_counts)
        p_anchor = choose_p_anchor(len(datasets) * len(landmarks), t_median_seconds, workers, hours)
        stage = "nine_datasets"
    if p_anchor is None:
        landmarks = ANCHOR_LANDMARKS[:2]
        p_anchor = choose_p_anchor(len(datasets) * len(landmarks), t_median_seconds, workers, hours)
        stage = "nine_datasets_two_landmarks"
    return {
        "status": "ok" if p_anchor is not None else "infeasible",
        "stage": stage,
        "datasets": list(datasets),
        "landmarks": list(landmarks),
        "n_instances": len(datasets) * len(landmarks),
        "p_anchor": p_anchor,
        "t_median_seconds": float(t_median_seconds),
        "workers": int(workers),
        "wall_clock_hours": float(hours),
    }


def timing_probe(evaluator, bank, rng, n_uncached=20) -> dict:
    """Measure real five-fold subset evaluations, excluding physical cache hits."""
    fields = tuple(bank)
    target = int(n_uncached)
    durations = []
    proposed = set()
    evaluator.proposal_count = getattr(evaluator, "proposal_count", 0)
    max_subsets = 2 ** len(fields) - 1
    try:
        while len(durations) < target and len(proposed) < max_subsets:
            k = int(rng.integers(1, len(fields) + 1))
            subset = frozenset(rng.choice(fields, size=k, replace=False).tolist())
            if subset in proposed:
                continue
            proposed.add(subset)
            evaluator.proposal_count += 1
            started = time.perf_counter()
            result = evaluator.evaluate(subset)
            elapsed = time.perf_counter() - started
            if result.status == "ok" and not result.physical_cache_hit:
                durations.append(elapsed)
    except BudgetExhausted:
        pass
    return {
        "requested_uncached": target,
        "measured_uncached": len(durations),
        "durations_seconds": durations,
        "t_median_seconds": statistics.median(durations) if durations else None,
        "complete": len(durations) == target,
    }


def combined_timing_median(probes) -> float:
    durations = [float(value) for probe in probes for value in probe.get("durations_seconds", ())]
    if not durations:
        raise ValueError("no uncached timing samples")
    return float(statistics.median(durations))


def build_anchor_plan_from_probes(probes, patient_counts, workers, hours=30.0) -> dict:
    """Validate the three 20-subset probes before applying the wall-clock rule."""
    probes = list(probes)
    by_dataset = {str(probe.get("dataset")): probe for probe in probes}
    incomplete = [
        dataset for dataset in ANCHOR_TIMING_DATASETS
        if dataset not in by_dataset or int(by_dataset[dataset].get("measured_uncached", 0)) < 20
    ]
    if incomplete:
        raise ValueError(f"ANCHOR requires 20 uncached timings for: {incomplete}")
    median = combined_timing_median(by_dataset[dataset] for dataset in ANCHOR_TIMING_DATASETS)
    return build_anchor_plan(patient_counts, median, workers, hours)


def anchor_fields(bank, univariate_rows, p_anchor) -> tuple[str, ...]:
    fields = tuple(bank)
    rows = sorted(univariate_rows, key=lambda row: (-float(row["c_index_mean"]), int(row["field_idx"])))
    selected = []
    for row in rows:
        idx = int(row["field_idx"])
        if 0 <= idx < len(fields) and fields[idx] not in selected:
            selected.append(fields[idx])
    return tuple(selected[: min(int(p_anchor), len(fields))])


class ExhaustiveSearcher(Searcher):
    name = "ANCHOR"

    def run(self, evaluator, bank, rng=None):
        if int(getattr(evaluator, "seed", 0)) != 0:
            raise ValueError("ANCHOR is defined only for seed 0")
        fields = tuple(bank)
        if len(fields) > 15:
            raise ValueError("ANCHOR field space must contain at most 15 fields")
        evaluator.proposal_count = 0
        best = ()
        best_score = float("-inf")
        reason = "field_space_exhausted"
        try:
            for k in range(1, len(fields) + 1):
                for names in itertools.combinations(fields, k):
                    evaluator.proposal_count += 1
                    result = evaluator.evaluate(frozenset(names))
                    value = score(result)
                    stable_names = result.subset
                    if value > best_score or (value == best_score and stable_names < best):
                        best, best_score = stable_names, value
        except BudgetExhausted:
            reason = "budget_exhausted"
        if not math.isfinite(best_score):
            best, best_score = (), 0.5
            reason = "evaluation_error"
        elif reason == "field_space_exhausted" and int(getattr(evaluator, "failures", 0)):
            reason = "evaluation_error"
        metadata = {
            "restricted_exact": reason == "field_space_exhausted",
            "restricted_fields": list(fields),
            "restricted_space_size": 2 ** len(fields) - 1,
        }
        return finish(self, evaluator, 0, best, best_score, reason, metadata=metadata)


def optimality_gap(anchor_best_cv_c, algorithm_best_cv_c) -> float:
    return float(anchor_best_cv_c) - float(algorithm_best_cv_c)
