from __future__ import annotations

import json
from pathlib import Path

from .config import k_grid
from .types import EvalResult


def load_univariate_rows(field_cindex_path, *, expected_fields, run_config_path=None,
                         expected_encoding="prompt", expected_modality="mlp_clinic_flatten",
                         expected_seed=0):
    """Read and validate the single-field table used by A0b/A6 priors."""
    import pandas as pd
    path = Path(field_cindex_path)
    frame = pd.read_csv(path)
    required = {"field", "field_idx", "c_index_mean"}
    if not required.issubset(frame.columns):
        raise ValueError(f"{path} missing columns: {sorted(required - set(frame.columns))}")
    found = set(frame["field"].astype(str))
    if found != set(expected_fields):
        raise ValueError("field_cindex field set does not match field_index.json")
    if run_config_path:
        config = json.loads(Path(run_config_path).read_text(encoding="utf-8"))
        if config.get("encoding", expected_encoding) != expected_encoding:
            raise ValueError("univariate encoding mismatch")
        if config.get("modality", expected_modality) != expected_modality:
            raise ValueError("univariate modality mismatch")
        if int(config.get("seed", 0)) != int(expected_seed):
            raise ValueError("univariate seed mismatch")
    return frame.to_dict("records")


def evaluate_full(evaluator, bank):
    return evaluator.evaluate(frozenset(bank))


class A0Full:
    name = "A0_full"
    def run(self, evaluator, bank, rng=None):
        return evaluate_full(evaluator, bank)


def top_k_subsets(evaluator, bank, univariate_rows):
    """Evaluate cumulative top-k fields; rows are sorted by c-index then field_idx."""
    fields = tuple(bank)
    rows = sorted(univariate_rows, key=lambda row: (-float(row["c_index_mean"]), int(row["field_idx"])))
    ordered = [fields[int(row["field_idx"])] for row in rows if 0 <= int(row["field_idx"]) < len(fields)]
    results = []
    for k in k_grid(len(fields)):
        subset = frozenset(ordered[:k])
        result = evaluator.evaluate(subset)
        results.append((k, result))
    valid = [(k, r) for k, r in results if r.status == "ok" and r.cv_c_mean is not None]
    best = min(valid, key=lambda kr: (-kr[1].cv_c_mean, kr[0])) if valid else (0, None)
    return {"path": results, "best_k": best[0], "best": best[1]}


class A0bTopK:
    name = "A0b_topk"
    def __init__(self, univariate_rows):
        self.univariate_rows = list(univariate_rows)
    def run(self, evaluator, bank, rng=None):
        return top_k_subsets(evaluator, bank, self.univariate_rows)
