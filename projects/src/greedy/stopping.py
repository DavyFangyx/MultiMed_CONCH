"""Pre-declared stopping rules for greedy paths (section 4.5).

Rules are applied after a full accumulation curve is collected:

- sig_stop: first k where the next K outer-fold ΔC values are jointly
  non-significant by a paired Wilcoxon test (p > 0.05 for K consecutive steps).
- 1se / parsimonious: smallest k whose mean outer-test c-index is within one
  standard error of the peak.
- best: k at the peak mean outer-test c-index.
"""

from __future__ import annotations

import math

import numpy as np


WILCOXON_ALPHA = 0.05


def _mean_std_se(values: list[float]) -> tuple[float, float, float]:
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    se = std / math.sqrt(n) if n > 0 else float("nan")
    return mean, std, se


def _paired_delta_p(before: list[float], after: list[float]) -> float:
    a = np.asarray(before, dtype=float)
    b = np.asarray(after, dtype=float)
    if a.shape != b.shape or len(a) == 0:
        return float("nan")
    diff = b - a
    if np.allclose(diff, 0.0):
        return 1.0
    try:
        from scipy.stats import wilcoxon

        result = wilcoxon(diff, alternative="greater", zero_method="wilcox")
        return float(result.pvalue)
    except Exception:
        # Fallback: sign test against 0. Enough for stub / tiny-n paths.
        n_pos = int(np.sum(diff > 0))
        n_neg = int(np.sum(diff < 0))
        n = n_pos + n_neg
        if n == 0:
            return 1.0
        from math import comb

        p = sum(comb(n, k) for k in range(n_pos, n + 1)) / (2 ** n)
        return float(p)


def summarize_step_scores(fold_records: list[dict]) -> list[dict]:
    """fold_records[*]['test_scores'] is a list of outer-test c-index by step."""
    if not fold_records:
        return []
    n_steps = min(len(rec.get("test_scores") or []) for rec in fold_records)
    rows = []
    if all("empty_test_score" in rec for rec in fold_records):
        prev_scores = [float(rec["empty_test_score"]) for rec in fold_records]
    else:
        prev_scores = None
    for k in range(n_steps):
        scores = [float(rec["test_scores"][k]) for rec in fold_records]
        mean, std, se = _mean_std_se(scores)
        delta = None
        p_value = None
        if prev_scores is not None:
            delta = [b - a for a, b in zip(prev_scores, scores)]
            p_value = _paired_delta_p(prev_scores, scores)
        rows.append(
            {
                "k": k + 1,
                "c_index_mean": mean,
                "c_index_std": std,
                "c_index_se": se,
                "delta_mean": float(np.mean(delta)) if delta is not None else 0.0,
                "delta_p": p_value,
                "scores": scores,
            }
        )
        prev_scores = scores
    return rows


def best_k(curve: list[dict]) -> int | None:
    if not curve:
        return None
    best = max(curve, key=lambda row: (row["c_index_mean"], -row["k"]))
    return int(best["k"])


def one_se_k(curve: list[dict]) -> int | None:
    peak = best_k(curve)
    if peak is None:
        return None
    peak_row = next(row for row in curve if row["k"] == peak)
    threshold = peak_row["c_index_mean"] - peak_row["c_index_se"]
    for row in curve:
        if row["c_index_mean"] + 1e-12 >= threshold:
            return int(row["k"])
    return peak


def sig_stop_k(curve: list[dict], patience: int = 3, alpha: float = WILCOXON_ALPHA) -> int | None:
    if not curve:
        return None
    patience = max(int(patience), 1)
    # A step is non-significant if its incoming ΔC has p > alpha (or NaN).
    # Consecutive K such steps trigger stop at the first of those K.
    flags = []
    for row in curve:
        p = row.get("delta_p")
        if p is None or (isinstance(p, float) and math.isnan(p)):
            flags.append(True)
        else:
            flags.append(float(p) > alpha)

    run = 0
    run_start = None
    for i, nonsig in enumerate(flags):
        if nonsig:
            if run == 0:
                run_start = curve[i]["k"] - 1  # last still-significant size
            run += 1
            if run >= patience:
                stopped = 0 if run_start is None else int(run_start)
                return max(stopped, 0)
        else:
            run = 0
            run_start = None
    return int(curve[-1]["k"])


def _subset_at(fold_records: list[dict], k: int | None) -> list[str]:
    if k is None or k <= 0 or not fold_records:
        return []
    # Consensus subset is not unique across folds; report the modal prefix
    # field names if present, otherwise the first fold's subset.
    names = []
    for rec in fold_records:
        path = rec.get("path") or []
        if len(path) >= k:
            names.append(tuple(path[k - 1].get("subset") or []))
    if not names:
        return []
    counts: dict[tuple, int] = {}
    for item in names:
        counts[item] = counts.get(item, 0) + 1
    best = max(counts.items(), key=lambda kv: (kv[1], ",".join(kv[0])))
    return list(best[0])


def apply_stopping_rules(fold_records: list[dict], patience: int = 3) -> dict:
    curve = summarize_step_scores(fold_records)
    peak = best_k(curve)
    parsimonious = one_se_k(curve)
    sig_stop = sig_stop_k(curve, patience=patience)
    points = {
        "best": {"k": peak, "subset": _subset_at(fold_records, peak), "rule": "peak_mean"},
        "parsimonious": {"k": parsimonious, "subset": _subset_at(fold_records, parsimonious), "rule": "1se"},
        "sig_stop": {"k": sig_stop, "subset": _subset_at(fold_records, sig_stop), "rule": "wilcoxon_patience"},
    }
    for name, point in points.items():
        row = next((r for r in curve if r["k"] == point["k"]), None)
        if row is not None:
            point["c_index_mean"] = row["c_index_mean"]
            point["c_index_std"] = row["c_index_std"]
            point["c_index_se"] = row["c_index_se"]
        else:
            point["c_index_mean"] = None
            point["c_index_std"] = None
            point["c_index_se"] = None
    return {"curve": curve, "points": points}
