"""Prompt-layer placeholder stats for human-defined L0-L5 schemes."""

from __future__ import annotations

from pathlib import Path
import re

import pandas as pd

from common.paths import dataset_prompt_dir

from .config import SCHEME_CONFIG, load_custom_schemes, resolve_scheme_names


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


def _contains_fallback(text: str, fallback_value: str) -> bool:
    t = str(text).strip().lower()
    fb = str(fallback_value).strip().lower()

    if fb in {"tx", "nx", "mx"}:
        return re.search(rf"\b{re.escape(fb)}\b", t) is not None

    if fb == "6":
        return re.search(r"(?<!\d)6(?!\d)", t) is not None

    return fb in t


def _pct_to_float(value):
    try:
        return float(str(value).replace("%", "")) / 100
    except Exception:
        return float("nan")


def analyze_prompt_layer(scheme: str, prompt_dir: str) -> pd.DataFrame:
    csv_file = Path(prompt_dir) / scheme / "prompts.csv"
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


def run_prompt_stats_one(scheme: str, prompt_dir: str, output_dir: Path, template_dir: str) -> pd.DataFrame:
    load_custom_schemes(template_dir)
    schemes = resolve_scheme_names(scheme)

    all_prompt_stats = []
    for name in schemes:
        print(f"\n{'='*60}")
        print(f"【Prompt CSV 分析】方案: {name}")
        print(f"{'='*60}")
        df_p = analyze_prompt_layer(name, prompt_dir)
        if df_p.empty:
            continue
        print(df_p.to_string(index=False))
        scheme_dir = Path(prompt_dir) / name
        scheme_dir.mkdir(parents=True, exist_ok=True)
        out_path = scheme_dir / "prompt_stats.csv"
        df_p.to_csv(out_path, index=False)
        print(f"\n✅ 已保存: {out_path}")
        all_prompt_stats.append(df_p)

    if not all_prompt_stats:
        return pd.DataFrame()

    merged = pd.concat(all_prompt_stats, ignore_index=True)
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
    return df_stats


def run_prompt_stats(args):
    from common.datasets import dataset_jobs, load_dataset_configs

    datasets = load_dataset_configs(args.datasets_config)
    jobs = dataset_jobs(
        args.dataset,
        datasets,
        json_path=args.json_path,
        prompt_dir=args.prompt_dir,
        out_dir=args.out,
        baseline_out=args.out,
    )
    for job in jobs:
        name = job["name"] or "custom"
        print(f"\n######## Dataset: {name} ########")
        prompt_dir = job["prompt_dir"] if job["name"] else (args.prompt_dir or dataset_prompt_dir(name))
        run_prompt_stats_one(args.scheme, prompt_dir, Path(prompt_dir), args.template_dir)
