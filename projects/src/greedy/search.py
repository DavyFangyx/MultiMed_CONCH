"""Greedy forward selection (section 4.3).

The inner loop adds the best remaining field while its c-index gain is at
least min_delta. After that, 4.5 stopping rules are applied to the
truncated curve.
"""

from __future__ import annotations

from .evaluator import extract_c_index
from concurrent.futures import ThreadPoolExecutor, as_completed


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
    init_idx=None,
    workers: int = 1,
    min_delta: float | None = 0.0,
):
    """Forward-select fields one at a time on the evaluator's current split.

    Returns path = [
      {"step": 1, "added": "diagnoses.ajcc_pathologic_n", "added_idx": 3,
       "delta_c": 0.031, "c_index": 0.612, "c_index_std": 0.0,
       "subset": [...], "subset_idx": [...], "all_candidates": {...}},
      ...
    ]

    Search stops at max_steps, when candidates run out, or when the best
    remaining field would raise c-index by less than min_delta. That field
    is not added. patience is still only recorded here; Wilcoxon patience
    is applied afterwards. min_delta=None disables the gain check.
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

    path = []
    selected: list[int] = []
    remaining = list(candidates)

    init_selected = []
    seen_init = set()
    for idx in list(init_idx or []):
        idx = int(idx)
        if idx in seen_init:
            continue
        if idx not in remaining:
            raise IndexError(f"init_idx out of remaining candidates: {idx}")
        seen_init.add(idx)
        init_selected.append(idx)

    if init_selected:
        init_result = evaluator.evaluate(init_selected)
        current, current_std = extract_c_index(init_result)
        selected = list(init_selected)
        remaining = [idx for idx in remaining if idx not in seen_init]
        path.append(
            {
                "step": 1,
                "added": ",".join(_field_name(fields, i) for i in selected),
                "added_idx": list(selected),
                "delta_c": 0.0,
                "c_index": float(current),
                "c_index_std": float(current_std),
                "subset": [_field_name(fields, i) for i in selected],
                "subset_idx": list(selected),
                "all_candidates": {},
                "patience": int(patience),
                "min_delta": None if min_delta is None else float(min_delta),
                "init": True,
            }
        )
        start_step = 2
        extra_steps = len(selected) - 1
        max_steps = min(max_steps + extra_steps, len(selected) + len(remaining))
    else:
        if empty_score is None:
            empty_result = evaluator.evaluate([])
            current, _ = extract_c_index(empty_result)
        else:
            current = float(empty_score)
        start_step = 1

    for step in range(start_step, max_steps + 1):
        all_candidates = {}
        best_idx = None
        best_score = None
        best_std = 0.0
        best_name = None
        n_workers = max(int(workers or 1), 1)

        def _eval_one(idx: int):
            name = _field_name(fields, idx)
            result = evaluator.evaluate(selected + [idx])
            score, std = extract_c_index(result)
            return idx, name, score, std

        scored = []
        if n_workers == 1 or len(remaining) <= 1:
            scored = [_eval_one(idx) for idx in remaining]
        else:
            with ThreadPoolExecutor(max_workers=min(n_workers, len(remaining))) as pool:
                futures = [pool.submit(_eval_one, idx) for idx in remaining]
                for fut in as_completed(futures):
                    scored.append(fut.result())

        for idx, name, score, std in scored:
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

        delta = float(best_score) - current
        if min_delta is not None and delta + 1e-12 < float(min_delta):
            break

        selected.append(best_idx)
        remaining.remove(best_idx)
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
                "min_delta": None if min_delta is None else float(min_delta),
            }
        )
        current = float(best_score)

    return path
