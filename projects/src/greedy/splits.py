"""5-fold split construction for greedy search.

One 5-fold split is shared by inner search and outer reporting. For each fold,
`val` and `test` are the same held-out patients. Inner evaluation uses
train/val; outer reporting uses test from the same files.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import json
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class NestedSplitConfig:
    outer_folds: int = 5
    repeats: int = 1
    seed: int = 0


@dataclass(frozen=True)
class FoldSplit:
    repeat: int
    fold: int
    fold_id: str
    train: list[str]
    val: list[str]
    test: list[str]
    inner_seed: int
    outer_seed: int


def _as_str_ids(patient_ids) -> list[str]:
    ids = [str(x) for x in list(patient_ids)]
    if len(ids) != len(set(ids)):
        raise ValueError("patient_ids must be unique")
    return ids


def _event_labels(patient_ids: list[str], events) -> np.ndarray:
    n = len(patient_ids)
    if events is None:
        return np.zeros(n, dtype=int)
    if isinstance(events, dict):
        return np.array([int(bool(events.get(pid, 0))) for pid in patient_ids], dtype=int)
    arr = np.asarray(list(events))
    if arr.shape[0] != n:
        raise ValueError("events length must match patient_ids")
    return arr.astype(int)


def _stratified_kfold_indices(labels: np.ndarray, n_splits: int, seed: int) -> list[np.ndarray]:
    rng = np.random.RandomState(seed)
    n = len(labels)
    if n_splits < 2:
        raise ValueError("outer_folds must be >= 2")
    if n < n_splits:
        raise ValueError(f"need at least {n_splits} patients, got {n}")

    folds = [[] for _ in range(n_splits)]
    for label in np.unique(labels):
        idx = np.where(labels == label)[0]
        rng.shuffle(idx)
        for i, sample in enumerate(idx):
            folds[i % n_splits].append(int(sample))
    return [np.array(sorted(fold), dtype=int) for fold in folds]


def build_nested_splits(patient_ids, events=None, config: NestedSplitConfig | None = None) -> list[FoldSplit]:
    cfg = config or NestedSplitConfig()
    ids = _as_str_ids(patient_ids)
    labels = _event_labels(ids, events)

    splits: list[FoldSplit] = []
    for repeat in range(cfg.repeats):
        outer_seed = int(cfg.seed) + repeat
        fold_indices = _stratified_kfold_indices(labels, cfg.outer_folds, outer_seed)
        all_idx = np.arange(len(ids))
        for fold, test_idx in enumerate(fold_indices):
            test_mask = np.zeros(len(ids), dtype=bool)
            test_mask[test_idx] = True
            train_ids = [ids[i] for i in all_idx[~test_mask]]
            held_out = sorted(ids[i] for i in test_idx)
            splits.append(
                FoldSplit(
                    repeat=repeat,
                    fold=fold,
                    fold_id=f"f{fold}" if cfg.repeats == 1 else f"r{repeat}_f{fold}",
                    train=sorted(train_ids),
                    val=held_out,
                    test=list(held_out),
                    inner_seed=outer_seed,
                    outer_seed=outer_seed,
                )
            )
    return splits


def splits_to_jsonable(splits: list[FoldSplit], config: NestedSplitConfig | None = None) -> dict:
    payload = {
        "n_folds": len(splits),
        "splits": [asdict(s) for s in splits],
    }
    if config is not None:
        payload["config"] = asdict(config)
    return payload


def splits_from_jsonable(payload: dict) -> list[FoldSplit]:
    rows = payload.get("splits", payload if isinstance(payload, list) else [])
    out = []
    for row in rows:
        out.append(
            FoldSplit(
                repeat=int(row["repeat"]),
                fold=int(row["fold"]),
                fold_id=str(row.get("fold_id") or f"r{row['repeat']}_f{row['fold']}"),
                train=[str(x) for x in row["train"]],
                val=[str(x) for x in row["val"]],
                test=[str(x) for x in row["test"]],
                inner_seed=int(row.get("inner_seed", 0)),
                outer_seed=int(row.get("outer_seed", 0)),
            )
        )
    return out


def save_nested_splits(path: Path | str, splits: list[FoldSplit], config: NestedSplitConfig | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(splits_to_jsonable(splits, config), f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def load_nested_splits(path: Path | str) -> list[FoldSplit]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return splits_from_jsonable(payload)


def write_analyzer_split_csv(path: Path | str, split: FoldSplit) -> Path:
    """Write one Clinic_Analyzer splits_0.csv from a nested FoldSplit."""
    import pandas as pd

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = max(len(split.train), len(split.val), len(split.test))
    def _pad(values: list[str]) -> list:
        out = list(values) + [None] * (n - len(values))
        return out[:n]

    df = pd.DataFrame({"train": _pad(split.train), "val": _pad(split.val), "test": _pad(split.test)})
    df.to_csv(path, index=True)
    return path


def write_analyzer_split_dir(out_dir: Path | str, splits: list[FoldSplit]) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for split in splits:
        write_analyzer_split_csv(out_dir / f"splits_{split.fold}.csv", split)
    return out_dir


def load_analyzer_split_dir(split_dir: Path | str) -> list[FoldSplit]:
    import pandas as pd

    split_dir = Path(split_dir)
    files = sorted(split_dir.glob("splits_*.csv"), key=lambda p: int(p.stem.split("_")[-1]))
    if not files:
        raise FileNotFoundError(f"no splits_*.csv under {split_dir}")
    splits = []
    for path in files:
        fold = int(path.stem.split("_")[-1])
        df = pd.read_csv(path)
        train = [str(x) for x in df["train"].dropna().tolist()]
        val = [str(x) for x in df["val"].dropna().tolist()] if "val" in df.columns else []
        test = [str(x) for x in df["test"].dropna().tolist()] if "test" in df.columns else list(val)
        if not val:
            val = list(test)
        splits.append(
            FoldSplit(
                repeat=0,
                fold=fold,
                fold_id=f"f{fold}",
                train=train,
                val=val,
                test=test,
                inner_seed=0,
                outer_seed=0,
            )
        )
    return splits
