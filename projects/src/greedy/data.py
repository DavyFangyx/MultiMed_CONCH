"""Load candidate fields, patient IDs, and event labels for greedy search."""

from __future__ import annotations

from dataclasses import dataclass

import json
from pathlib import Path

import pandas as pd

from common.patient_set import STUDY_BY_DISPLAY, display_to_study  # noqa: F401 (re-export)
from common.paths import dataset_field_bank_dir, dataset_kept_fields_path, encoding_and_landmark_tag_from_path, require_landmark_tag, validate_encoding


DEFAULT_ANALYZER_SPLIT_ROOT = Path(__file__).resolve().parents[2] / "Clinic_Analyzer" / "data" / "splits" / "5foldcv"
DEFAULT_ANALYZER_LABEL_ROOT = Path(__file__).resolve().parents[2] / "Clinic_Analyzer" / "data" / "datasets_csv" / "metadata"


def default_label_file_for(dataset: str, label_file: Path | str | None = None) -> Path | None:
    """搜索链路实际使用的默认 label 文件路径(与 load_survival_table 的默认分支一致)。

    不存在时返回 None,调用方在 cache key 中记 "missing"。用于把 label 内容哈希
    纳入评估缓存指纹(gt≤0 修复口径闸门)。
    """
    if label_file:
        path = Path(label_file)
        return path if path.exists() else None
    study = display_to_study(dataset)
    local = DEFAULT_ANALYZER_LABEL_ROOT / f"{study}.csv"
    return local if local.exists() else None


def default_analyzer_split_dir(dataset: str) -> Path:
    return DEFAULT_ANALYZER_SPLIT_ROOT / display_to_study(dataset)


def load_json(path: Path | str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _encoding_from_dirname(path: Path) -> str | None:
    encoding, _ = encoding_and_landmark_tag_from_path(path)
    return encoding


def _landmark_tag_from_dirname(path: Path) -> str | None:
    _, tag = encoding_and_landmark_tag_from_path(path)
    return tag


def load_field_bank(field_bank_dir: Path | str, encoding: str | None = None) -> dict:
    bank = Path(field_bank_dir)
    if not bank.exists():
        raise FileNotFoundError(f"field bank not found: {bank}")

    index_path = bank / "field_index.json"
    payload = load_json(index_path) if index_path.exists() else {}
    if not isinstance(payload, dict):
        payload = {}

    raw_encoding = payload.get("encoding")
    if raw_encoding:
        detected = validate_encoding(raw_encoding)
    else:
        detected = _encoding_from_dirname(bank)
        if detected is None and encoding is not None:
            detected = validate_encoding(encoding)
        elif detected is None:
            raise ValueError(
                f"cannot infer encoding for {bank}; expected field_index.json['encoding'] "
                "or a prompt/onehot directory name"
            )
        else:
            detected = validate_encoding(detected)

    if encoding is not None and validate_encoding(encoding) != detected:
        raise ValueError(f"encoding mismatch for {bank}: expected {encoding}, found {detected}")

    pt_dir = bank / "embeddings" / "pt"
    if not pt_dir.is_dir():
        pt_dir = bank / "pt"
    if not pt_dir.is_dir():
        pt_dir = bank

    fields = list(payload.get("fields") or [])
    return {
        "dir": bank,
        "pt_dir": pt_dir,
        "encoding": detected,
        "fields": fields,
        "index": payload,
        "n_fields": int(payload.get("n_fields") or len(fields) or 0),
    }


def load_candidate_fields(
    dataset: str,
    kept_fields_path: Path | str | None = None,
    field_index_path: Path | str | None = None,
    encoding: str = "prompt",
    landmark_tag: str | None = None,
    experiment: str | None = None,
) -> list[str]:
    if field_index_path:
        payload = load_json(field_index_path)
        fields = payload.get("fields")
        if not fields:
            raise ValueError(f"field_index has no fields: {field_index_path}")
        return list(fields)

    tag = require_landmark_tag(landmark_tag) if landmark_tag is not None else None
    if tag is not None:
        bank_index = dataset_field_bank_dir(dataset, encoding, tag, experiment=experiment) / "field_index.json"
        if bank_index.exists():
            return load_candidate_fields(dataset, field_index_path=bank_index)

    path = Path(kept_fields_path or dataset_kept_fields_path(dataset, tag))
    payload = load_json(path)
    if isinstance(payload, dict) and "fields" in payload:
        return list(payload["fields"])
    if isinstance(payload, dict) and dataset in payload:
        return list(payload[dataset]["fields"])
    raise KeyError(f"{dataset} not in {path}")


def unique_ids(values) -> list[str]:
    seen = set()
    out = []
    for value in values:
        pid = str(value)
        if pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
    return out


def load_patient_ids_from_field_bank(
    dataset: str,
    field_bank_dir: Path | str | None = None,
    encoding: str = "prompt",
    landmark_tag: str | None = None,
    experiment: str | None = None,
) -> list[str]:
    if field_bank_dir:
        bank = Path(field_bank_dir)
    else:
        bank = dataset_field_bank_dir(dataset, encoding, landmark_tag, experiment=experiment)
    if bank.exists():
        loaded = load_field_bank(bank, encoding=encoding)
        bank = loaded["dir"]
        pt_dir = loaded["pt_dir"]
    else:
        pt_dir = bank / "embeddings" / "pt"
    prompt_path = bank / "prompts.csv"
    if prompt_path.exists():
        df = pd.read_csv(prompt_path)
        col = "patient_id" if "patient_id" in df.columns else df.columns[0]
        return unique_ids(df[col].tolist())
    if pt_dir.is_dir():
        return unique_ids(sorted(p.stem for p in pt_dir.glob("*.pt")))
    return []


def load_survival_table(dataset: str, label_file: Path | str | None = None) -> pd.DataFrame:
    """读 label CSV（仅本地；2026-10-06 解耦后无 PGC 回退，缺失即报错）。"""
    if label_file:
        path = Path(label_file)
    else:
        path = DEFAULT_ANALYZER_LABEL_ROOT / f"{display_to_study(dataset)}.csv"
    if not path.exists():
        raise FileNotFoundError(f"label file not found: {path}")
    df = pd.read_csv(path)
    if "case_id" not in df.columns:
        raise ValueError(f"{path} has no case_id column")
    return df


def load_events(dataset: str, patient_ids: list[str], label_file: Path | str | None = None) -> dict[str, int]:
    df = load_survival_table(dataset, label_file=label_file)
    if "censorship" not in df.columns:
        return {pid: 0 for pid in patient_ids}
    # SurvPGC: censorship=1 means censored, 0 means event.
    events = {}
    for _, row in df.iterrows():
        pid = str(row["case_id"])
        censored = int(row["censorship"])
        events[pid] = 0 if censored == 1 else 1
    return {pid: int(events.get(pid, 0)) for pid in patient_ids}


def resolve_patient_set(
    dataset: str,
    field_bank_dir: Path | str | None = None,
    label_file: Path | str | None = None,
    encoding: str = "prompt",
    landmark_tag: str | None = None,
) -> tuple[list[str], dict[str, int]]:
    bank_ids = load_patient_ids_from_field_bank(
        dataset, field_bank_dir=field_bank_dir, encoding=encoding, landmark_tag=landmark_tag
    )
    try:
        labels = load_survival_table(dataset, label_file=label_file)
        label_ids = unique_ids(labels["case_id"].tolist())
    except FileNotFoundError:
        labels = None
        label_ids = []

    if bank_ids and label_ids:
        keep = unique_ids(pid for pid in bank_ids if pid in set(label_ids))
    elif bank_ids:
        keep = unique_ids(bank_ids)
    else:
        keep = unique_ids(label_ids)
    if not keep:
        raise ValueError(f"no patients found for {dataset}")

    if labels is None:
        events = {pid: 0 for pid in keep}
    else:
        events = load_events(dataset, keep, label_file=label_file)
    return keep, events


# --- 5 折 CSV 读取(原 greedy/splits.py,2026-10-13 随死链删除迁入;唯一消费者 = univariate)---

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
