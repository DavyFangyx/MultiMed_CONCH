#!/usr/bin/env python3
"""S5b / Test_1a 两臂一致性抽查：off 臂(raw) 与 t0 臂 的 (dataset, field) 逐折患者集必须逐位相同。

对每个 (dataset, field_idx)：
  ① 两侧 bank 的 field_index.json 在该 idx 上的字段名必须一致（raw 变体 = lm0 字段集同序）；
  ② 逐折 splits_{i}.csv（train/val/test 三列）患者集合必须完全一致；
  ③ 逐折 split_{i}_results{,_val}.pkl 的键集合必须完全一致（analyzer 实际评估的患者）；
  ④ 打印两臂该字段的 c-index（5 折均值）与 Δc = c(off) − c(t0)（若有）。

用法（base python 3.13.12，不训练）：
    python scripts/s5b_audit_arms.py --pair TCGA-BLCA:0 TCGA-BLCA:1 TCGA-BRCA:0
    python scripts/s5b_audit_arms.py --pair-file pairs.txt   # 每行 dataset:field_idx
产物：results/Test_1a/arm_off/_audit_pairs.json（追加更新）
"""

from __future__ import annotations

import argparse
import csv
import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from common.paths import test_results_dir
from greedy.embeddings import subset_scheme_name

LM0_RESULTS = test_results_dir("Test_1a/arm_t0") / "prompt" / "landmark_0"
RAW_RESULTS = test_results_dir("Test_1a/arm_off") / "univariate" / "prompt" / "landmark_none"
RAW_BANK_ROOT = ROOT / "outputs" / "_raw"
LM0_BANK_ROOT = ROOT / "outputs"
MODALITY = "mlp_clinic_flatten"
N_FOLDS = 5
OUT_JSON = test_results_dir("Test_1a/arm_off") / "_audit_pairs.json"


def bank_fields(dataset: str, raw: bool) -> list[str]:
    root = RAW_BANK_ROOT if raw else LM0_BANK_ROOT
    tag = "landmark_none" if raw else "landmark_0"
    index = json.loads((root / dataset / "field_bank" / "prompt" / tag / "field_index.json").read_text(encoding="utf-8"))
    return list(index["fields"])


def fold_patient_sets(run_dir: Path) -> list[dict[str, set[str]] | None]:
    folds = []
    for i in range(N_FOLDS):
        path = run_dir / f"splits_{i}.csv"
        if not path.exists():
            folds.append(None)  # 该折还没跑到（训练进行中）
            continue
        with open(path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        folds.append({col: {row[col] for row in rows if row.get(col)} for col in ("train", "val", "test")})
    return folds


def pkl_keys(run_dir: Path) -> list[set[str] | None]:
    keys = []
    for i in range(N_FOLDS):
        path = run_dir / f"split_{i}_results.pkl"
        if not path.exists():
            keys.append(None)  # 该折尚未写出（训练进行中）
            continue
        with open(path, "rb") as f:
            keys.append(set(pickle.load(f).keys()))
    return keys


def cindex_from_csv(dataset: str, field: str, root: Path) -> float | None:
    path = root / dataset / MODALITY / "field_cindex.csv"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("field") == field and row.get("status") == "ok":
                try:
                    return float(row["c_index_mean"])
                except (TypeError, ValueError):
                    return None
    return None


def value_diff_summary(dataset: str) -> dict:
    """raw 变体与 lm0 的取值差异摘要（构建期由 s5b_build_raw_field_bank.py 落盘）。"""
    path = RAW_BANK_ROOT / dataset / "field_bank" / "prompt" / "landmark_none" / "raw_value_diff.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("summary") or {}
    per_field = {}
    for item in payload.get("fields") or []:
        per_field[str(item.get("field"))] = item
    return {"summary": summary, "fields": per_field}


def audit_pair(dataset: str, field_idx: int) -> dict:
    raw_fields = bank_fields(dataset, raw=True)
    lm0_fields = bank_fields(dataset, raw=False)
    result = {"dataset": dataset, "field_idx": int(field_idx), "ok": False, "checks": {}, "notes": []}
    if field_idx >= len(raw_fields) or field_idx >= len(lm0_fields):
        result["notes"].append(f"field_idx 越界 raw={len(raw_fields)} lm0={len(lm0_fields)}")
        return result
    field = raw_fields[field_idx]
    result["field"] = field
    result["field_name_match"] = raw_fields[field_idx] == lm0_fields[field_idx]
    # 取值差异（mask 影响的证据）：该字段在两个变体下的取值是否变化，以及数据集中
    # 非 timed 家族的改动字段数（必须为 0——取值差异只允许出现在会被 mask 影响的字段）。
    diff = value_diff_summary(dataset)
    item = (diff.get("fields") or {}).get(field) or {}
    result["raw_value_changed"] = bool(int(float(item.get("changed_cells") or 0)) > 0)
    result["raw_value_changed_cells"] = int(float(item.get("changed_cells") or 0))
    result["raw_value_timed_family"] = bool(item.get("timed_family"))
    if diff:
        untimed = list((diff.get("summary") or {}).get("untimed_changed_fields") or [])
        result["untimed_changed_fields"] = untimed
        result["untimed_changed_ok"] = not untimed
    scheme = subset_scheme_name([int(field_idx)])
    result["scheme"] = scheme
    t0_dir = LM0_RESULTS / dataset / "runs" / scheme / MODALITY
    raw_dir = RAW_RESULTS / dataset / "runs" / scheme / MODALITY
    result["t0_run_dir"] = str(t0_dir)
    result["raw_run_dir"] = str(raw_dir)
    if not t0_dir.exists() or not raw_dir.exists():
        result["notes"].append(f"run dir 缺失 t0={t0_dir.exists()} raw={raw_dir.exists()}")
        return result

    t0_folds = fold_patient_sets(t0_dir)
    raw_folds = fold_patient_sets(raw_dir)
    split_folds = [i for i in range(N_FOLDS) if t0_folds[i] is not None and raw_folds[i] is not None]
    split_pending = [i for i in range(N_FOLDS) if i not in split_folds]
    split_ok = all(
        all(t0_folds[i][col] == raw_folds[i][col] for col in ("train", "val", "test"))
        for i in split_folds
    )
    if not split_ok:
        for i in split_folds:
            for col in ("train", "val", "test"):
                if t0_folds[i][col] != raw_folds[i][col]:
                    result["notes"].append(
                        f"fold{i}.{col} 差异: t0-raw={sorted(t0_folds[i][col] - raw_folds[i][col])[:3]} "
                        f"raw-t0={sorted(raw_folds[i][col] - t0_folds[i][col])[:3]}"
                    )
    t0_keys = pkl_keys(t0_dir)
    raw_keys = pkl_keys(raw_dir)
    # 只比较两侧都已写出的折；缺失折记为 pending（训练进行中），不算失败，
    # 但因 pending 而不算"完整通过"，需在字段跑完后重跑本脚本。
    compared = [i for i in range(N_FOLDS) if t0_keys[i] is not None and raw_keys[i] is not None]
    pending = sorted(set(split_pending) | {i for i in range(N_FOLDS) if i not in compared})
    pkl_ok = all(t0_keys[i] == raw_keys[i] for i in compared) and bool(compared)
    result["checks"] = {
        "splits_identical": split_ok,
        "splits_folds_compared": split_folds,
        "splits_folds_pending": split_pending,
        "pkl_keys_identical": pkl_ok,
        "pkl_folds_compared": compared,
        "pkl_folds_pending": [i for i in range(N_FOLDS) if i not in compared],
        "n_patients_per_fold_t0": [
            None if folds is None else len(folds["val"]) + len(folds["train"]) + len(folds["test"])
            for folds in t0_folds
        ],
        "n_pkl_keys_t0": [len(keys) if keys is not None else None for keys in t0_keys],
        "n_pkl_keys_raw": [len(keys) if keys is not None else None for keys in raw_keys],
    }
    for i in compared:
        if t0_keys[i] != raw_keys[i]:
            result["notes"].append(
                f"fold{i} pkl 键差异: t0-raw={sorted(t0_keys[i] - raw_keys[i])[:3]} "
                f"raw-t0={sorted(raw_keys[i] - t0_keys[i])[:3]}"
            )
    if not split_ok:
        for i in range(N_FOLDS):
            for col in ("train", "val", "test"):
                if t0_folds[i][col] != raw_folds[i][col]:
                    result["notes"].append(
                        f"fold{i}.{col} 差异: t0-raw={sorted(t0_folds[i][col] - raw_folds[i][col])[:3]} "
                        f"raw-t0={sorted(raw_folds[i][col] - t0_folds[i][col])[:3]}"
                    )
    c_t0 = cindex_from_csv(dataset, field, LM0_RESULTS)
    c_raw = cindex_from_csv(dataset, field, RAW_RESULTS)
    result["c_index_t0"] = c_t0
    result["c_index_off"] = c_raw
    if c_t0 is not None and c_raw is not None:
        result["delta_c"] = round(c_raw - c_t0, 6)
    result["complete"] = not pending
    result["ok"] = bool(
        result["field_name_match"]
        and split_ok
        and pkl_ok
        and not pending
        and result.get("untimed_changed_ok", True)
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Test_1a 两臂 (dataset,field) 一致性抽查")
    parser.add_argument("--pair", nargs="*", default=[], help="dataset:field_idx，如 TCGA-BLCA:0")
    parser.add_argument("--pair-file", default=None, help="每行 dataset:field_idx")
    args = parser.parse_args()
    pairs = list(args.pair)
    if args.pair_file:
        pairs.extend(
            line.strip()
            for line in Path(args.pair_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        )
    if not pairs:
        parser.error("至少给一个 --pair dataset:field_idx 或 --pair-file")
    results = []
    for item in pairs:
        dataset, _, idx = item.partition(":")
        results.append(audit_pair(dataset.strip(), int(idx)))
    print(f"{'dataset':12s} {'idx':>3s} {'field':52s} {'name':>4s} {'splits':>6s} {'pkl':>4s} {'value':>5s} {'c_t0':>7s} {'c_off':>7s} {'dC':>8s}")
    for r in results:
        checks = r.get("checks") or {}
        pkl_cell = "OK" if checks.get("pkl_keys_identical") else ("..." if checks.get("pkl_folds_pending") else "X")
        split_cell = "OK" if checks.get("splits_identical") else ("..." if checks.get("splits_folds_pending") else "X")
        val_cell = "mask" if r.get("raw_value_changed") else "same"
        if r.get("untimed_changed_ok") is False:
            val_cell = "BAD"
        print(
            f"{r['dataset']:12s} {r['field_idx']:3d} {str(r.get('field'))[:52]:52s} "
            f"{'OK' if r.get('field_name_match') else 'X':>4s} "
            f"{split_cell:>6s} "
            f"{pkl_cell:>4s} "
            f"{val_cell:>5s} "
            f"{str(r.get('c_index_t0'))[:7]:>7s} {str(r.get('c_index_off'))[:7]:>7s} "
            f"{str(r.get('delta_c'))[:8]:>8s}"
        )
        for note in r.get("notes") or []:
            print(f"    note: {note}")
    payload = {}
    if OUT_JSON.exists():
        try:
            payload = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    pairs_map = payload.setdefault("pairs", {})
    for r in results:
        pairs_map[f"{r['dataset']}:{r['field_idx']}"] = r
    payload["n_pairs"] = len(pairs_map)
    payload["n_complete"] = sum(1 for r in pairs_map.values() if r.get("complete"))
    payload["all_ok"] = all(bool(r.get("ok")) for r in pairs_map.values())
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[s5b] audit json: {OUT_JSON}  complete={payload['n_complete']}/{payload['n_pairs']} all_ok={payload['all_ok']}")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
