from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .cache import SQLiteCache, make_cache_key
from .config import N_FOLDS, budget_for
from .types import BudgetExhausted, EvalResult


def _hash_file(path):
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()


class Evaluator:
    """E2 adapter around the existing ClinicSubsetEvaluator.

    ``inner`` may be any object exposing ``evaluate(subset_idx)``; this keeps
    algorithm tests independent of Clinic Analyzer while production reuses the
    existing evaluator unchanged.
    """

    def __init__(self, inner, fields, *, budget=None, seed=0, cache=None,
                 dataset="", landmark_tag="", encoding="prompt",
                     modality="mlp_clinic_flatten", field_index_hash="",
                 split_hashes=(), train_args_hash="", jsonl_path=None,
                 run_id="", algorithm="", field_indices=None):
        self.inner, self.fields = inner, tuple(fields)
        self.field_indices = tuple(range(len(self.fields))) if field_indices is None else tuple(int(i) for i in field_indices)
        if len(self.field_indices) != len(self.fields) or len(set(self.field_indices)) != len(self.field_indices):
            raise ValueError("field_indices must be a unique index for every field")
        self.seed = int(seed)
        self.budget = budget_for(len(self.fields)) if budget is None else int(budget)
        self.logical_evals = 0
        self.physical_trains = 0
        self.cache_hits = 0
        self.failures = 0
        self._seen = {}
        self.cache = cache if isinstance(cache, SQLiteCache) or cache is None else SQLiteCache(cache)
        self._cache_args = dict(dataset=dataset, landmark_tag=landmark_tag, encoding=encoding,
                                modality=modality, seed=self.seed,
                                field_index_hash=field_index_hash, split_hashes=split_hashes,
                                train_args_hash=train_args_hash)
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None
        self.run_id, self.algorithm = str(run_id), str(algorithm)
        self.dataset, self.landmark_tag, self.encoding, self.modality = dataset, landmark_tag, encoding, modality

    def _write(self, payload):
        if not self.jsonl_path:
            return
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with self.jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")

    def evaluate(self, subset: frozenset[str]) -> EvalResult:
        raw_names = set(subset)
        unknown = [name for name in raw_names if name not in self.fields]
        if unknown:
            raise KeyError(f"unknown fields: {unknown}")
        names = tuple(sorted(
            raw_names, key=lambda name: self.field_indices[self.fields.index(name)]
        ))
        idx = tuple(self.field_indices[self.fields.index(name)] for name in names)
        if not idx:
            return EvalResult((), (), 0, 0.5, (0.5,) * N_FOLDS, 0, False, 0, "ok")
        keyset = frozenset(names)
        if keyset in self._seen:
            # Searchers should normally filter repeats. Returning the prior result
            # makes accidental duplicate proposals harmless and non-consuming.
            return self._seen[keyset]
        if self.logical_evals >= self.budget:
            raise BudgetExhausted(f"logical budget exhausted ({self.budget})")
        self.logical_evals += 1
        logical_idx = self.logical_evals
        started = time.perf_counter()
        cache_hit = False
        payload = None
        if self.cache is not None:
            key = make_cache_key(**self._cache_args, fields=names)
            payload = self.cache.get(key)
            cache_hit = payload is not None
        try:
            if payload is None:
                self.physical_trains += 1
                raw = self.inner.evaluate(list(idx))
                folds = tuple(float(x) for x in raw.get("per_fold", raw.get("cv_folds", ())))
                mean = raw.get("c_index_mean", raw.get("cv_c_mean"))
                if len(folds) != N_FOLDS or any(not __import__('math').isfinite(x) for x in folds) or mean is None:
                    raise ValueError("evaluation must return five finite fold c-index values")
                mean = float(mean)
                if not __import__('math').isfinite(mean):
                    raise ValueError("cv_c_mean is not finite")
                payload = {"cv_c_mean": mean, "cv_folds": folds}
                if self.cache is not None:
                    self.cache.put(key, payload)
            else:
                self.cache_hits += 1
            result = EvalResult(names, idx, len(idx), float(payload["cv_c_mean"]),
                                tuple(payload["cv_folds"]), logical_idx, cache_hit,
                                int((time.perf_counter() - started) * 1000), "ok")
        except Exception as exc:
            self.failures += 1
            result = EvalResult(names, idx, len(idx), None, (), logical_idx, cache_hit,
                                int((time.perf_counter() - started) * 1000), "error", str(exc)[:500])
        self._seen[keyset] = result
        self._write({"run_id": self.run_id, "dataset": self.dataset,
                     "landmark_tag": self.landmark_tag, "encoding": self.encoding,
                     "modality": self.modality, "algo": self.algorithm, "seed": self.seed,
                     "proposal_idx": int(getattr(self, "proposal_count", logical_idx)),
                     "subset": list(names), "subset_idx": list(idx), "k": len(idx),
                     "logical_eval_idx": logical_idx, "cv_c_mean": result.cv_c_mean,
                     "cv_folds": list(result.cv_folds), "physical_cache_hit": cache_hit,
                     "wall_ms": result.wall_ms, "status": result.status,
                     "meta": {},
                     **({"error": result.error} if result.error else {})})
        return result

    def precharge(self, single_field_results=None) -> None:
        """Reserve the p single-field evaluations used as an algorithm prior."""
        if self.logical_evals:
            raise RuntimeError("precharge must happen before evaluations")
        self.logical_evals = min(len(self.fields), self.budget)
        scores = single_field_results
        if scores is None:
            scores = getattr(self, "univariate_scores", None)
        if scores is not None and len(scores) == len(self.fields):
            self.cache_hits += min(len(self.fields), self.budget)
            for idx, value in enumerate(scores):
                name = self.fields[idx]
                all_folds = getattr(self, "univariate_folds", None)
                folds = tuple(float(x) for x in all_folds[idx]) if all_folds is not None else (float(value),) * N_FOLDS
                if len(folds) != N_FOLDS:
                    raise ValueError("univariate prior must provide five folds per field")
                self._seen[frozenset((name,))] = EvalResult(
                    (name,), (self.field_indices[idx],), 1, float(value), folds,
                    idx + 1, True, 0, "ok"
                )
                self._write({"run_id": self.run_id, "dataset": self.dataset,
                             "landmark_tag": self.landmark_tag, "encoding": self.encoding,
                             "modality": self.modality, "algo": self.algorithm, "seed": self.seed,
                             "proposal_idx": idx + 1, "logical_eval_idx": idx + 1,
                             "subset": [name], "subset_idx": [self.field_indices[idx]], "k": 1,
                             "cv_c_mean": float(value), "cv_folds": list(folds),
                             "physical_cache_hit": True, "wall_ms": 0, "status": "ok",
                             "meta": {"univariate_prior": True}})
