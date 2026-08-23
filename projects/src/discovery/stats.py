"""JSON full-field statistics for scanned field dictionaries."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from common.clinical_io import load_clinical_cases
from common.datasets import get_dataset_clinic_files, get_dataset_project_ids, load_dataset_configs, resolve_dataset_names
from common.fields import collapse_patient_values, extract_path_values, is_array_field
from common.missingness import classify_raw_value
from common.paths import REGISTRY_DIR, dataset_field_stats_path
from common.types import infer_type, to_numeric
from common.fields import L5_PLACEHOLDER_BY_FIELD_PATH

from .scan import load_json_field_dictionary, parse_field_dictionary, resolve_json_field_dict_path


def _calc_entropy(values: list) -> tuple:
    if not values:
        return (float("nan"), float("nan"), 0, "", float("nan"))

    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1

    n = len(values)
    k = len(counts)
    probs = [c / n for c in counts.values()]
    entropy = -sum(p * math.log2(p) for p in probs if p > 0)
    entropy_norm = entropy / math.log2(k) if k > 1 else 0.0
    top1_value, top1_count = max(counts.items(), key=lambda t: t[1])
    return (entropy, entropy_norm, k, str(top1_value), top1_count / n)


def _calc_variance(values: list) -> tuple:
    nums = [x for x in values if isinstance(x, (int, float))]
    if not nums:
        return (float("nan"), float("nan"), float("nan"))
    n = len(nums)
    mean = sum(nums) / n
    var = sum((x - mean) ** 2 for x in nums) / n
    return (mean, var, math.sqrt(var))


def analyze_json_all_fields(json_path, json_field_dict: str, project_ids: list | None = None) -> pd.DataFrame:
    print(f"\n{'='*60}")
    print("【JSON 全字段统计】")
    print(f"  JSON            : {json_path}")
    print(f"  字段字典        : {json_field_dict}")
    print(f"{'='*60}")

    cases = load_clinical_cases(json_path, project_ids=project_ids)
    patient_total = len(cases)
    print(f"  纳入病例数      : {patient_total}")
    if patient_total == 0:
        print("  ⚠️  纳入病例数为 0，跳过全字段统计")
        return pd.DataFrame()

    dict_path = Path(json_field_dict)
    if not dict_path.exists():
        print(f"  ⚠️  字段字典不存在: {dict_path}")
        return pd.DataFrame()

    dict_data = load_json_field_dictionary(dict_path)
    fields = parse_field_dictionary(dict_data)
    print(f"  字段总数        : {len(fields)}")

    rows = []
    for fd in fields:
        field_path = fd["field_path"]
        field_name = fd["field_name"]
        patient_values = []
        valid_count = null_count = sentinel_count = absent_count = multi_record_count = 0

        for case in cases:
            raw_vals = extract_path_values(case, field_path)
            if not raw_vals:
                absent_count += 1
                continue
            if len(raw_vals) > 1:
                multi_record_count += 1
            states = [classify_raw_value(v) for v in raw_vals]
            valid_vals = [v for v, st in zip(raw_vals, states) if st == "valid"]
            if valid_vals:
                valid_count += 1
                patient_values.append(collapse_patient_values(valid_vals))
            elif any(st == "sentinel" for st in states):
                sentinel_count += 1
            else:
                null_count += 1

        total_count = patient_total
        missing_count = total_count - valid_count
        missing_rate = missing_count / total_count if total_count else 0.0
        coverage = valid_count / total_count if total_count else 0.0
        null_rate = null_count / total_count if total_count else 0.0
        sentinel_rate = sentinel_count / total_count if total_count else 0.0
        multi_record = is_array_field(field_path)
        multi_record_rate = multi_record_count / total_count if total_count else 0.0

        non_empty_clean = [v for v in patient_values if v is not None]
        numeric_vals = []
        numeric_all = True
        for v in non_empty_clean:
            n = to_numeric(v)
            if n is None:
                numeric_all = False
                break
            numeric_vals.append(n)

        if not non_empty_clean:
            value_kind = "empty"
            unique_count = 0
            info_metric_type = "none"
            info_metric_value = 0.0
            mode_value = ""
            mode_share = 0.0
        elif numeric_all:
            value_kind = "numeric"
            unique_count = len(set(numeric_vals))
            _, var, _ = _calc_variance(numeric_vals)
            info_metric_type = "variance"
            info_metric_value = 0.0 if math.isnan(var) else round(var, 6)
            _, _, _, mode_value, mode_share = _calc_entropy(non_empty_clean)
        else:
            value_kind = "categorical"
            _, entropy_norm, unique_count, mode_value, mode_share = _calc_entropy(non_empty_clean)
            info_metric_type = "entropy_norm"
            info_metric_value = 0.0 if math.isnan(entropy_norm) else round(entropy_norm, 6)

        prompt_placeholder = L5_PLACEHOLDER_BY_FIELD_PATH.get(field_path, "")
        rows.append(
            {
                "field_path": field_path,
                "section": fd["section"],
                "layer": field_path.split(".")[0].replace("[]", "") if "." in field_path else "case",
                "total": total_count,
                "missing": missing_count,
                "valid": valid_count,
                "missing_rate": f"{missing_rate:.1%}",
                "value_kind": value_kind,
                "unique_count": unique_count,
                "info_metric_type": info_metric_type,
                "info_metric_value": info_metric_value,
                "coverage": round(coverage, 6),
                "absent_count": absent_count,
                "null_count": null_count,
                "sentinel_count": sentinel_count,
                "null_rate": round(null_rate, 6),
                "sentinel_rate": round(sentinel_rate, 6),
                "mode_value": str(mode_value)[:80],
                "mode_share": round(float(mode_share or 0.0), 6),
                "example_values": " | ".join(str(v)[:80] for v in non_empty_clean[:5]),
                "inferred_type": infer_type(field_name, non_empty_clean, unique_count),
                "multi_record": multi_record,
                "multi_record_rate": round(multi_record_rate, 6),
                "used_in_l0_l5": bool(prompt_placeholder),
                "prompt_placeholder": prompt_placeholder,
                "_missing_rate": missing_rate,
            }
        )

    df = pd.DataFrame(rows)
    df = df.sort_values(["_missing_rate", "field_path"], ascending=[False, True]).drop(columns=["_missing_rate"])
    return df.reset_index(drop=True)


def run_field_stats(args):
    datasets = load_dataset_configs(args.datasets_config)
    dataset_names = [] if not args.dataset else resolve_dataset_names(args.dataset, datasets)
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

    jobs = []
    if not dataset_names:
        jobs.append({"name": "custom", "json_paths": [args.json_path], "project_ids": []})
    else:
        for name in dataset_names:
            jobs.append(
                {
                    "name": name,
                    "json_paths": get_dataset_clinic_files(name, datasets),
                    "project_ids": get_dataset_project_ids(name, datasets),
                }
            )

    frames = []
    for job in jobs:
        name = job["name"]
        print(f"\n######## Dataset: {name} ########")
        dict_path = resolve_json_field_dict_path(dataset_name=name, explicit_path=args.json_field_dict)
        if not Path(dict_path).exists():
            print(f"  ⚠️  未找到字段字典: {dict_path}")
            print("     请先运行: python projects/scripts/run_scan_fields.py --dataset {name}")
            continue
        df = analyze_json_all_fields(job["json_paths"], str(dict_path), project_ids=job["project_ids"])
        if df.empty:
            continue
        out_path = dataset_field_stats_path(name)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        print(f"\n✅ JSON 全字段统计已保存: {out_path}")
        frames.append(df.assign(dataset=name))

    if len(frames) >= 1:
        merged = pd.concat(frames, ignore_index=True)
        cols = ["dataset"] + [c for c in merged.columns if c != "dataset"]
        merged = merged[cols].sort_values(["dataset", "missing", "field_path"], ascending=[True, False, True])
        out_path = REGISTRY_DIR / "field_stats_raw.csv"
        merged.to_csv(out_path, index=False)
        print(f"\n✅ 跨数据集统计已保存: {out_path}")
