"""Load existing Clinic_Analyzer 5-fold CSVs for greedy search.

Greedy does not generate splits. It reads splits_*.csv with columns
train,val,test from Clinic_Analyzer/data/splits/5foldcv/{study}/.
For each fold, val and test are the same held-out patients.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
        missing = [col for col in ("train", "val", "test") if col not in df.columns]
        if missing:
            raise ValueError(f"{path} missing columns: {missing}")
        train = [str(x) for x in df["train"].dropna().tolist()]
        val = [str(x) for x in df["val"].dropna().tolist()]
        test = [str(x) for x in df["test"].dropna().tolist()]
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
