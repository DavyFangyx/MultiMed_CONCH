"""
analysis.py — 字段缺失率 / 占位率 / 信息量分析

功能概览
========
1) JSON 语义缺失率（extract_values 口径）
2) Prompt CSV 占位率与并集汇总
3) JSON 全字段统计（基于字段字典）
   - 输出: json_layer_stats_all.csv
   - 指标: 非空率、信息熵/方差

conda activate trident
python CONCH-main/projects/scripts/run_missing_rate_analysis.py --scheme all --json_all_fields true
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

import pandas as pd

from pipeline import (
    DEFAULT_DATASETS_CONFIG,
    DEFAULT_JSON_PATH,
    DEFAULT_PROMPT_DIR,
    DEFAULT_TEMPLATE_DIR,
    SCHEME_CONFIG,
    SCHEME_PROMPT_FILE,
    dataset_prompt_dir,
    extract_values,
    get_dataset_clinic_files,
    get_dataset_project_ids,
    load_clinical_cases,
    load_dataset_configs,
    load_custom_schemes,
    resolve_dataset_names,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ─────────────────────────────────────────────────────────
# 1. 全局配置
# ─────────────────────────────────────────────────────────
FIELD_FALLBACKS = {
    "SUBTYPE": "Unknown Neoplasm",
    "TUMORSTAGE": "Stage X",
    "EDITION": "6",
    "RACE": "not reported",
    "DIAGNOSIS": "Unknown Neoplasm",
    "AGE": "unknown",
    "SEX": "not reported",
    "SEX_AT_BIRTH": "not reported",
    "ETHNICITY": "not reported",
    "PRIMARY_SITE": "not reported",
    "PRIMARY_DIAGNOSIS": "Unknown Neoplasm",
    "MORPHOLOGY": "not reported",
    "TISSUE_OR_ORGAN_OF_ORIGIN": "not reported",
    "LATERALITY": "not reported",
    "YEAR_OF_DIAGNOSIS": "not reported",
    "AGE_AT_DIAGNOSIS": "unknown",
    "AJCC_PATHOLOGIC_STAGE": "Stage X",
    "AJCC_PATHOLOGIC_T": "TX",
    "AJCC_PATHOLOGIC_N": "NX",
    "AJCC_PATHOLOGIC_M": "MX",
    "AJCC_STAGING_SYSTEM_EDITION": "not reported",
    "TUMOR_GRADE": "not reported",
    "PRIOR_MALIGNANCY": "not reported",
    "SYNCHRONOUS_MALIGNANCY": "not reported",
    "TREATMENT_TYPE": "not reported",
    "TREATMENT_OR_THERAPY": "not reported",
    "TREATMENT_INTENT_TYPE": "not reported",
    "PRIOR_TREATMENT": "not reported",
    "TOBACCO_SMOKING_STATUS": "not reported",
    "PROGRESSION_OR_RECURRENCE": "not reported",
    "LYMPH_NODES_TESTED": "not reported",
    "LYMPH_NODES_POSITIVE": "not reported",
    "ECOG_PERFORMANCE_STATUS": "not reported",
    "BMI": "not reported",
}

INVALID_TEXTS = {
    "",
    "not reported",
    "unknown",
    "not applicable",
    "--",
}

SECTION_PREFIX_MAP = {
    "顶层字段": "",
    "project对象": "project",
    "demographic对象": "demographic",
    "diagnoses数组_每个对象": "diagnoses[]",
    "diagnoses.pathology_details数组_每个对象": "diagnoses[].pathology_details[]",
    "diagnoses.treatments数组_每个对象": "diagnoses[].treatments[]",
    "exposures数组_每个对象": "exposures[]",
    "follow_ups数组_每个对象": "follow_ups[]",
    "follow_ups.molecular_tests数组_每个对象": "follow_ups[].molecular_tests[]",
    "follow_ups.other_clinical_attributes数组_每个对象": "follow_ups[].other_clinical_attributes[]",
}

DEFAULT_JSON_FIELD_DICT = str(PROJECT_ROOT / "templates/l0_l5/json_field_dictionary.json")
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "stats"


def _str2bool(v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"无法解析布尔值: {v}")


# ─────────────────────────────────────────────────────────
# 2. 第一层：JSON 语义缺失率（extract_values 口径）
# ─────────────────────────────────────────────────────────
def analyze_json_layer(json_path, project_ids: list | None = None) -> pd.DataFrame:
    print(f"\n{'='*60}")
    print("【第一层】JSON 语义缺失率分析")
    print(f"  JSON       : {json_path}")
    print(f"{'='*60}")

    cases = load_clinical_cases(json_path, project_ids=project_ids)
    print(f"  JSON 总病例: {len(cases)}")
    if not cases:
        print("  ⚠️  JSON 中无病例，跳过分析。")
        return pd.DataFrame()

    field_names = list(FIELD_FALLBACKS.keys())
    counts = {f: {"missing": 0, "total": 0} for f in field_names}

    for case in cases:
        vals = extract_values(case)
        for field in field_names:
            v = vals.get(field, "")
            counts[field]["total"] += 1
            if str(v).strip().lower() == FIELD_FALLBACKS[field].lower():
                counts[field]["missing"] += 1

    rows = []
    for field in field_names:
        total = counts[field]["total"]
        missing = counts[field]["missing"]
        valid = total - missing
        rate = missing / total if total else 0.0
        rows.append(
            {
                "field": field,
                "fallback_value": FIELD_FALLBACKS[field],
                "total": total,
                "missing": missing,
                "valid": valid,
                "missing_rate": f"{rate:.1%}",
                "_rate_float": rate,
            }
        )

    df = pd.DataFrame(rows).sort_values("_rate_float", ascending=False).drop(columns="_rate_float")
    df = df.reset_index(drop=True)
    print("\n" + df.to_string(index=False))
    return df


# ─────────────────────────────────────────────────────────
# 3. 第二层：Prompt CSV 占位率 + 信息量
# ─────────────────────────────────────────────────────────
def _contains_fallback(text: str, fallback_value: str) -> bool:
    t = str(text).strip().lower()
    fb = str(fallback_value).strip().lower()

    if fb in {"tx", "nx", "mx"}:
        return re.search(rf"\\b{re.escape(fb)}\\b", t) is not None

    if fb == "6":
        return re.search(r"(?<!\\d)6(?!\\d)", t) is not None

    return fb in t


def analyze_prompt_layer(scheme: str, prompt_dir: str) -> pd.DataFrame:
    csv_file = Path(prompt_dir) / SCHEME_PROMPT_FILE[scheme]
    if not csv_file.exists():
        print(f"  ⚠️  [{scheme}] prompt CSV 不存在: {csv_file}，请先运行 json2prompt")
        return pd.DataFrame()

    df = pd.read_csv(csv_file)
    n = len(df)
    if n == 0:
        print(f"  ⚠️  [{scheme}] prompt CSV 中无患者")
        return pd.DataFrame()

    prompt_cols = SCHEME_CONFIG[scheme]["output_cols"]
    placeholders = SCHEME_CONFIG[scheme]["placeholders"]
    col_to_placeholder = dict(zip(prompt_cols, placeholders))

    rows = []
    for col in prompt_cols:
        if col not in df.columns:
            continue
        series = df[col]
        null_count = series.isna().sum() + (series.astype(str).str.strip() == "").sum()

        placeholder_key = col_to_placeholder.get(col, "")
        if placeholder_key and placeholder_key in FIELD_FALLBACKS:
            fallback_value = FIELD_FALLBACKS[placeholder_key]
            placeholder_count = series.apply(lambda x: _contains_fallback(x, fallback_value)).sum()
        else:
            placeholder_count = 0

        vc = series.value_counts(dropna=False)
        top1_val = str(vc.index[0]) if len(vc) else ""
        top1_cnt = int(vc.iloc[0]) if len(vc) else 0

        rate_ph = placeholder_count / n
        rate_null = null_count / n

        rows.append(
            {
                "scheme": scheme,
                "column": col,
                "total": n,
                "placeholder_count": int(placeholder_count),
                "placeholder_rate": f"{rate_ph:.1%}",
                "null_rate": f"{rate_null:.1%}",
                "unique_count": int(series.nunique(dropna=True)),
                "top1_ratio": f"{top1_cnt/n:.1%}",
                "top1_value": top1_val[:60],
                "_ph_float": rate_ph,
            }
        )

    df_out = pd.DataFrame(rows).sort_values("_ph_float", ascending=False).drop(columns="_ph_float")
    return df_out.reset_index(drop=True)


# ─────────────────────────────────────────────────────────
# 4. 第三层：JSON 全字段统计（字典驱动）
# ─────────────────────────────────────────────────────────
def _parse_field_dictionary(dict_data: dict) -> list:
    fields = []
    for section, body in dict_data.items():
        if section in {"说明", "通用字段补充说明"}:
            continue
        if section not in SECTION_PREFIX_MAP:
            continue
        if not isinstance(body, dict):
            continue

        prefix = SECTION_PREFIX_MAP[section]
        for key, zh in body.items():
            field_path = f"{prefix}.{key}" if prefix else key
            fields.append(
                {
                    "section": section,
                    "field_path": field_path,
                    "field_name": key,
                    "field_zh": str(zh),
                }
            )
    return fields


def _extract_path_values(case: dict, field_path: str) -> list:
    tokens = field_path.split(".") if field_path else []
    nodes = [case]

    for token in tokens:
        is_array = token.endswith("[]")
        key = token[:-2] if is_array else token
        nxt = []

        for node in nodes:
            if not isinstance(node, dict):
                continue
            if key not in node:
                continue
            val = node.get(key)

            if is_array:
                if isinstance(val, list):
                    nxt.extend(val)
            else:
                nxt.append(val)

        nodes = nxt

    return nodes


def _is_non_empty_value(v) -> bool:
    if v is None:
        return False

    if isinstance(v, str):
        s = v.strip()
        if not s:
            return False
        return s.lower() not in INVALID_TEXTS

    if isinstance(v, list):
        return len(v) > 0

    if isinstance(v, dict):
        return len(v) > 0

    return True


def _to_numeric(v):
    try:
        if isinstance(v, bool):
            return float(int(v))
        return float(v)
    except Exception:
        return None


def _collapse_patient_values(values: list):
    if not values:
        return None

    scalar_vals = []
    for x in values:
        if isinstance(x, (dict, list)):
            scalar_vals.append(json.dumps(x, ensure_ascii=False, sort_keys=True))
        else:
            scalar_vals.append(str(x).strip())

    nums = []
    all_numeric = True
    for x in scalar_vals:
        n = _to_numeric(x)
        if n is None:
            all_numeric = False
            break
        nums.append(n)

    if all_numeric and nums:
        return sum(nums) / len(nums)

    uniq = sorted(set(scalar_vals))
    if len(uniq) == 1:
        return uniq[0]
    return " | ".join(uniq)


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
    top1_ratio = top1_count / n

    return (entropy, entropy_norm, k, str(top1_value), top1_ratio)


def _calc_variance(values: list) -> tuple:
    nums = [x for x in values if isinstance(x, (int, float))]
    if not nums:
        return (float("nan"), float("nan"), float("nan"))

    n = len(nums)
    mean = sum(nums) / n
    var = sum((x - mean) ** 2 for x in nums) / n
    std = math.sqrt(var)
    return (mean, var, std)


def analyze_json_all_fields(
    json_path,
    json_field_dict: str,
    project_ids: list | None = None,
) -> pd.DataFrame:
    print(f"\n{'='*60}")
    print("【第三层】JSON 全字段统计（字典驱动）")
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

    with open(dict_path, "r", encoding="utf-8") as f:
        dict_data = json.load(f)

    fields = _parse_field_dictionary(dict_data)
    print(f"  字段总数        : {len(fields)}")

    rows = []
    for fd in fields:
        field_path = fd["field_path"]
        patient_values = []
        non_empty_count = 0

        for case in cases:
            raw_vals = _extract_path_values(case, field_path)
            valid_vals = [v for v in raw_vals if _is_non_empty_value(v)]
            if valid_vals:
                non_empty_count += 1
                patient_values.append(_collapse_patient_values(valid_vals))

        valid_count = non_empty_count
        total_count = patient_total
        missing_count = total_count - valid_count
        missing_rate = missing_count / total_count if total_count else 0.0

        non_empty_clean = [v for v in patient_values if v is not None]
        numeric_vals = []
        numeric_all = True
        for v in non_empty_clean:
            n = _to_numeric(v)
            if n is None:
                numeric_all = False
                break
            numeric_vals.append(n)

        if not non_empty_clean:
            value_kind = "empty"
            unique_count = 0
            info_metric_type = "none"
            info_metric_value = 0.0
        elif non_empty_clean and numeric_all:
            value_kind = "numeric"
            unique_count = len(set(numeric_vals))
            _, var, _ = _calc_variance(numeric_vals)
            info_metric_type = "variance"
            info_metric_value = 0.0 if math.isnan(var) else round(var, 6)
        else:
            value_kind = "categorical"
            _, entropy_norm, unique_count, _, _ = _calc_entropy(non_empty_clean)
            info_metric_type = "entropy_norm"
            info_metric_value = 0.0 if math.isnan(entropy_norm) else round(entropy_norm, 6)

        rows.append(
            {
                "field_path": field_path,
                "section": fd["section"],
                "total": total_count,
                "missing": missing_count,
                "valid": valid_count,
                "missing_rate": f"{missing_rate:.1%}",
                "value_kind": value_kind,
                "unique_count": unique_count,
                "info_metric_type": info_metric_type,
                "info_metric_value": info_metric_value,
                "_missing_rate": missing_rate,
            }
        )

    df = pd.DataFrame(rows)
    df = df.sort_values(["_missing_rate", "field_path"], ascending=[False, True]).drop(columns=["_missing_rate"])
    return df.reset_index(drop=True)


# ─────────────────────────────────────────────────────────
# 5. 汇总 + 输出
# ─────────────────────────────────────────────────────────
def run_one(args, json_paths, prompt_dir: str, output_dir: Path, project_ids: list | None = None):
    load_custom_schemes(args.template_dir)

    if not SCHEME_CONFIG:
        print("未找到任何方案，请确认 template_dir 下存在 custom_schemes.json")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 第一层：JSON（extract_values 口径） ───────────────
    df_json = analyze_json_layer(json_paths, project_ids=project_ids)
    if not df_json.empty:
        out_path = output_dir / "json_layer_stats.csv"
        df_json.to_csv(out_path, index=False)
        print(f"\n✅ JSON 层统计已保存: {out_path}")

    # ── 第二层：Prompt CSV ──────────────────────────────
    schemes = list(SCHEME_CONFIG.keys()) if args.scheme == "all" else [args.scheme]

    all_prompt_stats = []
    for scheme in schemes:
        print(f"\n{'='*60}")
        print(f"【第二层】Prompt CSV 分析  方案: {scheme}")
        print(f"{'='*60}")
        df_p = analyze_prompt_layer(scheme, prompt_dir)
        if df_p.empty:
            continue
        print(df_p.to_string(index=False))
        out_path = output_dir / f"prompt_layer_{scheme}.csv"
        df_p.to_csv(out_path, index=False)
        print(f"\n✅ 已保存: {out_path}")
        all_prompt_stats.append(df_p)

    if all_prompt_stats:
        merged = pd.concat(all_prompt_stats, ignore_index=True)
        merged_path = output_dir / "prompt_layer_all_schemes.csv"
        merged.to_csv(merged_path, index=False)
        print(f"\n✅ 所有方案合并统计已保存: {merged_path}")

        print(f"\n{'='*60}")
        print("【汇总】各方案 × 字段 placeholder_rate 对照表")
        print(f"{'='*60}")
        pivot = merged.copy()
        pivot["_ph"] = pivot["placeholder_rate"]
        try:
            pt = pivot.pivot_table(index="column", columns="scheme", values="_ph", aggfunc="first")
            print(pt.fillna("—").to_string())
        except Exception:
            pass

        print(f"\n{'='*60}")
        print("【并集汇总】所有字段跨方案统一视图  →  prompt_layer_stats.csv")
        print(f"{'='*60}")

        def _pct_to_float(s):
            try:
                return float(str(s).replace("%", "")) / 100
            except Exception:
                return float("nan")

        merged["_ph_f"] = merged["placeholder_rate"].apply(_pct_to_float)

        stats_rows = []
        for col, grp in merged.groupby("column", sort=False):
            ph_min = grp["_ph_f"].min()
            ph_max = grp["_ph_f"].max()
            ph_str = f"{ph_min:.1%}" if ph_min == ph_max else f"{ph_min:.1%}~{ph_max:.1%}"
            stats_rows.append(
                {
                    "column": col,
                    "schemes": ", ".join(sorted(grp["scheme"].unique())),
                    "placeholder_rate": ph_str,
                    "ph_rate_max": f"{ph_max:.1%}",
                    "_ph_max": ph_max,
                }
            )

        df_stats = (
            pd.DataFrame(stats_rows)
            .sort_values("_ph_max", ascending=False)
            .drop(columns="_ph_max")
            .reset_index(drop=True)
        )

        print(df_stats.to_string(index=False))

        stats_path = output_dir / "prompt_layer_stats.csv"
        df_stats.to_csv(stats_path, index=False)
        print(f"\n✅ 字段并集统计已保存: {stats_path}")

    # ── 第三层：JSON 全字段统计（可开关，默认开启） ───────
    if args.json_all_fields:
        df_json_all = analyze_json_all_fields(
            json_path=json_paths,
            json_field_dict=args.json_field_dict,
            project_ids=project_ids,
        )
        if not df_json_all.empty:
            out_path = output_dir / "json_layer_stats_all.csv"
            df_json_all.to_csv(out_path, index=False)
            print("\n" + df_json_all.head(20).to_string(index=False))
            print(f"\n✅ JSON 全字段统计已保存: {out_path}")

    print(f"\n所有结果保存于: {output_dir}")


def run(args):
    datasets = load_dataset_configs(args.datasets_config)
    dataset_names = resolve_dataset_names(args.dataset, datasets)

    if not dataset_names:
        run_one(
            args=args,
            json_paths=[args.json_path],
            prompt_dir=args.prompt_dir,
            output_dir=OUTPUT_DIR,
            project_ids=[],
        )
        return

    for name in dataset_names:
        print(f"\n######## Dataset: {name} ########")
        run_one(
            args=args,
            json_paths=get_dataset_clinic_files(name, datasets),
            prompt_dir=dataset_prompt_dir(name),
            output_dir=PROJECT_ROOT / "outputs" / name / "stats",
            project_ids=get_dataset_project_ids(name, datasets),
        )


# ─────────────────────────────────────────────────────────
# 6. CLI
# ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="字段缺失率 / 占位率 / 信息量分析（JSON + Prompt）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--scheme", default="all", help="方案名（all = 全部；默认如 L0 / L1 / ... / L5）")
    parser.add_argument("--dataset", default=None, help="数据集名；支持 all 或逗号分隔列表。为空时使用 --json_path 单数据集模式。")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG, help="数据集 clinical JSON 配置文件")
    parser.add_argument("--json_path", default=DEFAULT_JSON_PATH)
    parser.add_argument("--template_dir", default=DEFAULT_TEMPLATE_DIR)
    parser.add_argument("--prompt_dir", default=DEFAULT_PROMPT_DIR)

    # 新增：JSON 全字段统计开关（默认开启）
    parser.add_argument(
        "--json_all_fields",
        type=_str2bool,
        default=True,
        help="是否执行 JSON 全字段统计并输出 json_layer_stats_all.csv（默认: true）",
    )
    parser.add_argument(
        "--json_field_dict",
        default=DEFAULT_JSON_FIELD_DICT,
        help="JSON 字段字典文件路径（默认: projects/templates/l0_l5/json_field_dictionary.json）",
    )
    run(parser.parse_args())


if __name__ == "__main__":
    main()
