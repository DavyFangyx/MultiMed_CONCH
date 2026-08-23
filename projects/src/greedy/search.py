"""Greedy forward selection (section 4.3).

The inner loop never early-stops. Run the full accumulation curve so 4.5
stopping rules can be applied afterwards.
"""

from __future__ import annotations

from .evaluator import extract_c_index


def _field_name(fields: list[str], idx: int) -> str:
    if 0 <= idx < len(fields):
        return fields[idx]
    return str(idx)


def greedy_forward(
    evaluator,
    candidate_idx=None,
    max_steps=None,
    patience: int = 3,
    empty_score: float | None = None,
):
    """Forward-select fields one at a time on the evaluator's current split.

    Returns path = [
      {"step": 1, "added": "diagnoses.ajcc_pathologic_n", "added_idx": 3,
       "delta_c": 0.031, "c_index": 0.612, "c_index_std": 0.0,
       "subset": [...], "subset_idx": [...], "all_candidates": {...}},
      ...
    ]

    `patience` is recorded but not used to break. The search always runs to
    max_steps or until every candidate is consumed.
    """
    fields = list(getattr(evaluator, "fields", []))
    if candidate_idx is None:
        candidates = list(range(len(fields)))
    else:
        candidates = [int(i) for i in list(candidate_idx)]
        unknown = [i for i in candidates if i < 0 or (fields and i >= len(fields))]
        if unknown:
            raise IndexError(f"candidate_idx out of range: {unknown}")

    seen = set()
    unique_candidates = []
    for idx in candidates:
        if idx not in seen:
            seen.add(idx)
            unique_candidates.append(idx)
    candidates = unique_candidates

    if max_steps is None:
        max_steps = len(candidates)
    max_steps = min(int(max_steps), len(candidates))

    selected: list[int] = []
    if empty_score is None:
        empty_result = evaluator.evaluate([])
        current, _ = extract_c_index(empty_result)
    else:
        current = float(empty_score)
    path = []

    remaining = list(candidates)
    for step in range(1, max_steps + 1):
        all_candidates = {}
        best_idx = None
        best_score = None
        best_std = 0.0
        best_name = None
        for idx in remaining:
            name = _field_name(fields, idx)
            result = evaluator.evaluate(selected + [idx])
            score, std = extract_c_index(result)
            all_candidates[name] = {
                "c_index": score,
                "c_index_std": std,
                "idx": idx,
            }
            better = best_score is None or score > best_score + 1e-12
            if not better and best_score is not None and abs(score - best_score) <= 1e-12:
                better = name < str(best_name)
            if better:
                best_idx = idx
                best_score = score
                best_std = std
                best_name = name
        if best_idx is None:
            break

        selected.append(best_idx)
        remaining.remove(best_idx)
        delta = float(best_score) - current
        path.append(
            {
                "step": step,
                "added": best_name,
                "added_idx": best_idx,
                "delta_c": delta,
                "c_index": float(best_score),
                "c_index_std": float(best_std),
                "subset": [_field_name(fields, i) for i in selected],
                "subset_idx": list(selected),
                "all_candidates": all_candidates,
                "patience": int(patience),
            }
        )
        current = float(best_score)

    return path
