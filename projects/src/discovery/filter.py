"""R0-R6 field filtering and Field Bank manifest generation."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from common.paths import (
    DEFAULT_FIELD_FILTER_RULES,
    dataset_exclusion_log_path,
    dataset_field_bank_template_dir,
    dataset_field_registry_path,
    dataset_filter_log_dir,
    dataset_kept_fields_path,
    dataset_stats_dir,
    shared_field_stats_path,
    shared_kept_fields_path,
)
from .landmark import iter_landmark_args, landmark_dir_tag, parse_landmark_options


DEFAULT_R3_COVERAGE = 0.30
DEFAULT_R4_N_UNIQUE = 2
DEFAULT_R4_MODE_SHARE = 0.95
POST_BASELINE_LAYERS = {"follow_ups", "other_clinical_attributes"}

_RULES_CACHE: dict[str, dict] | None = None


def _leaf_name(field_path: str) -> str:
    return str(field_path).split(".")[-1].replace("[]", "")


def _norm(field_path: str) -> str:
    return str(field_path).replace("[]", "").lower()


def timepoint(field_path: str) -> str:
    parts = {p.replace("[]", "") for p in str(field_path).split(".")}
    if parts & POST_BASELINE_LAYERS:
        return "follow_up"
    return "baseline"


def load_filter_rules(path=None) -> dict:
    global _RULES_CACHE
    rules_path = Path(path) if path else DEFAULT_FIELD_FILTER_RULES
    cache_key = str(rules_path.resolve()) if rules_path.exists() else str(rules_path)
    if _RULES_CACHE is not None and _RULES_CACHE.get("_path") == cache_key:
        return _RULES_CACHE["data"]
    if not rules_path.exists():
        raise FileNotFoundError(f"未找到字段筛选名单: {rules_path}")
    with open(rules_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"字段筛选名单必须是 JSON object: {rules_path}")
    _RULES_CACHE = {"_path": cache_key, "data": data}
    return data


def _as_lower_set(values) -> set[str]:
    return {str(v).strip().lower() for v in (values or []) if str(v).strip()}


def _path_has_token(field_path: str, token: str) -> bool:
    needle = str(token).strip().lower()
    if not needle:
        return False
    parts = [p.replace("[]", "").lower() for p in str(field_path).split(".")]
    return needle in parts


def _path_matches_suffix(field_path: str, suffix: str) -> bool:
    raw = str(field_path)
    target = str(suffix).strip()
    if not target:
        return False
    return raw == target or raw.endswith("." + target) or raw.endswith(target)


def apply_rules(
    row: pd.Series,
    min_coverage: float = DEFAULT_R3_COVERAGE,
    min_unique: int = DEFAULT_R4_N_UNIQUE,
    max_mode_share: float = DEFAULT_R4_MODE_SHARE,
    rules: dict | None = None,
    no_landmark: bool = False,
) -> tuple[str | None, str]:
    """Apply R0-R5 in document order. R2/R6 are markers, not drop rules."""
    field_path = str(row["field_path"])
    leaf = _leaf_name(field_path).lower()
    norm = _norm(field_path)
    rules = rules or load_filter_rules()
    r0 = rules.get("R0_label_leak") or {}
    r1 = rules.get("R1_admin") or {}
    r5_drop = {}
    for group in (rules.get("R5_derivable") or {}).get("groups") or []:
        keep = [str(v).strip() for v in (group.get("keep") or []) if str(v).strip()]
        note = str(group.get("note") or "").strip()
        trigger = f"keep {', '.join(keep)}" if keep else note
        for leaf_name in group.get("drop") or []:
            key = str(leaf_name).strip().lower()
            if key:
                r5_drop[key] = trigger or key

    # R0: label leakage. Hard exclusion, never skip.
    r0_except = _as_lower_set(r0.get("except_leaves"))
    if leaf not in r0_except:
        if leaf in _as_lower_set(r0.get("leaves")):
            return "R0_label_leak", leaf
        if any(token in leaf or token in norm for token in _as_lower_set(r0.get("substrings"))):
            return "R0_label_leak", leaf
        if no_landmark and any(_path_has_token(field_path, token) for token in (r0.get("path_contains") or [])):
            return "R0_label_leak", f"path_contains:{leaf}"
        if any(_path_matches_suffix(field_path, suffix) for suffix in (r0.get("path_suffixes") or [])):
            return "R0_label_leak", leaf
        if any(leaf.startswith(prefix) for prefix in (r0.get("leaf_startswith") or [])):
            return "R0_label_leak", leaf

    # R1: administrative / identifier fields.
    if leaf in _as_lower_set(r1.get("leaves")) or any(
        leaf.endswith(suffix) for suffix in (r1.get("leaf_endswith") or [])
    ):
        return "R1_admin", leaf
    if leaf in _as_lower_set(r1.get("container_leaves")):
        return "R1_admin", f"container:{leaf}"

    # R2 is a marker only; see timepoint().

    # R3: coverage threshold.
    coverage = float(row.get("coverage") or 0.0)
    if coverage < min_coverage:
        return "R3_coverage", f"{coverage:.6f}<{min_coverage}"

    # R4: degenerate fields.
    n_unique = int(row.get("unique_count") or 0)
    mode_share = float(row.get("mode_share") or 0.0)
    if n_unique < min_unique:
        return "R4_degenerate", f"n_unique={n_unique}"
    if mode_share > max_mode_share:
        return "R4_degenerate", f"mode_share={mode_share:.6f}"

    # Extra derivable-field drops kept from the current registry.
    if leaf in r5_drop:
        return "R5_derivable", r5_drop[leaf]

    return None, ""


def _portability(n_present: int, n_datasets: int) -> str:
    if n_datasets <= 0:
        return "local"
    ratio = n_present / n_datasets
    if ratio >= 0.80:
        return "universal"
    if ratio >= 0.50:
        return "common"
    return "local"


def _aggregate_inferred_type(series: pd.Series) -> str:
    values = [
        str(v).strip()
        for v in series.dropna().tolist()
        if str(v).strip() and str(v).strip().lower() not in {"nan", "none"}
    ]
    if not values:
        return ""
    if "ordinal_stage" in values:
        return "ordinal_stage"
    return pd.Series(values).mode().iloc[0]


def _iqr(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(series.quantile(0.75) - series.quantile(0.25))


def _example_value(row: pd.Series) -> str:
    raw = str(row.get("example_values") or "").strip()
    if raw and raw.lower() not in {"nan", "none"}:
        return raw.split("|")[0].strip()
    mode = str(row.get("mode_value") or "").strip()
    if mode and mode.lower() not in {"nan", "none"}:
        return mode
    return ""


def _build_registry_row(field, src, kept, excluded, n_present, n_datasets, keep=None) -> dict:
    if keep is None:
        keep = n_present > 0
    excluded_by = "" if keep else ",".join(sorted(excluded["rule"].unique())) if not excluded.empty else ""
    coverage_series = kept["coverage"] if keep and not kept.empty else src["coverage"]
    unique_series = kept["n_unique"] if keep and not kept.empty else src["unique_count"]
    mode_series = kept["mode_share"] if keep and not kept.empty else src["mode_share"]
    inferred_src = kept if keep and not kept.empty else src
    inferred = _aggregate_inferred_type(inferred_src.get("inferred_type", pd.Series(dtype=object)))
    return {
        "field": field,
        "timepoint": timepoint(field),
        "inferred_type": inferred,
        "portability": _portability(n_present, n_datasets),
        "n_datasets_present": n_present,
        "coverage_median": round(float(coverage_series.median()) if len(coverage_series) else 0.0, 6),
        "coverage_iqr": round(_iqr(coverage_series.astype(float)), 6),
        "n_unique_median": round(float(unique_series.median()) if len(unique_series) else 0.0, 6),
        "mode_share_median": round(float(mode_series.median()) if len(mode_series) else 0.0, 6),
        "excluded_by": excluded_by,
        "keep": keep,
        "note": "R2 marks follow_up; R6 marks portability only",
    }


def run_field_filter(args):
    stats_path = Path(args.stats_csv) if args.stats_csv else shared_field_stats_path()
    if not stats_path.exists():
        raise FileNotFoundError(
            f"未找到统计表: {stats_path}。请先运行 python projects/scripts/run_field_stats.py --dataset all"
        )

    df = pd.read_csv(stats_path)
    if "dataset" not in df.columns:
        df = df.copy()
        df.insert(0, "dataset", args.dataset or "custom")
    if args.dataset and args.dataset not in {"all", ""}:
        wanted = {x.strip() for x in args.dataset.split(",") if x.strip()}
        df = df[df["dataset"].astype(str).isin(wanted)].copy()

    datasets = sorted(df["dataset"].astype(str).unique().tolist())
    scan_roots = [dataset_stats_dir(dataset) for dataset in datasets]
    for landmark_args in iter_landmark_args(args, scan_roots=scan_roots, context="field filter"):
        _run_field_filter_one(landmark_args, df)


def _run_field_filter_one(args, df: pd.DataFrame) -> None:
    tag = landmark_dir_tag(args)
    args.landmark_tag = tag

    exclusion_rows = []
    keep_rows = []
    for _, row in df.iterrows():
        rule, trigger = apply_rules(
            row,
            min_coverage=getattr(args, "R3_coverage", DEFAULT_R3_COVERAGE),
            min_unique=getattr(args, "R4_n_unique", DEFAULT_R4_N_UNIQUE),
            max_mode_share=getattr(args, "R4_mode_share", DEFAULT_R4_MODE_SHARE),
            rules=load_filter_rules(getattr(args, "filter_rules", None)),
            no_landmark=not parse_landmark_options(args)[0],
        )
        item = {
            "dataset": row["dataset"],
            "field": row["field_path"],
            "coverage": float(row.get("coverage") or 0.0),
            "n_unique": int(row.get("unique_count") or 0),
            "mode_share": float(row.get("mode_share") or 0.0),
            "inferred_type": row.get("inferred_type") or "",
            "n_patients": int(row.get("total") or 0),
            "timepoint": timepoint(row["field_path"]),
        }
        if rule:
            exclusion_rows.append(
                {
                    "dataset": item["dataset"],
                    "field": item["field"],
                    "rule": rule,
                    "trigger": trigger,
                    "coverage": item["coverage"],
                    "n_unique": item["n_unique"],
                    "mode_share": item["mode_share"],
                    "timepoint": item["timepoint"],
                }
            )
        else:
            keep_rows.append(item)

    exclusion_df = pd.DataFrame(exclusion_rows)
    keep_df = pd.DataFrame(keep_rows)
    n_datasets = df["dataset"].nunique()

    registry_rows = []
    all_fields = sorted(df["field_path"].astype(str).unique())

    for field in all_fields:
        src = df[df["field_path"].astype(str) == field]
        kept = keep_df[keep_df["field"] == field] if not keep_df.empty else pd.DataFrame()
        excluded = exclusion_df[exclusion_df["field"] == field] if not exclusion_df.empty else pd.DataFrame()
        n_present = len(kept)

        registry_rows.append(_build_registry_row(field, src, kept, excluded, n_present, n_datasets))

    registry_df = pd.DataFrame(registry_rows).sort_values(["keep", "field"], ascending=[False, True])

    active = {}
    if not keep_df.empty:
        for dataset, grp in keep_df.groupby("dataset"):
            fields = sorted(grp["field"].astype(str).tolist())
            coverage = {
                row.field: float(row.coverage)
                for row in grp.itertuples(index=False)
            }
            n_patients = int(grp["n_patients"].iloc[0]) if len(grp) else 0
            active[dataset] = {
                "n_patients": n_patients,
                "fields": fields,
                "coverage": {k: coverage[k] for k in fields},
            }

    datasets = sorted(df["dataset"].astype(str).unique().tolist())
    for dataset in datasets:
        log_dir = dataset_filter_log_dir(dataset, tag)
        log_dir.mkdir(parents=True, exist_ok=True)

        ds_exclusion = (
            exclusion_df[exclusion_df["dataset"].astype(str) == dataset].copy()
            if not exclusion_df.empty
            else pd.DataFrame()
        )
        ds_keep = (
            keep_df[keep_df["dataset"].astype(str) == dataset].copy()
            if not keep_df.empty
            else pd.DataFrame()
        )

        ds_src = df[df["dataset"].astype(str) == dataset]
        ds_registry_rows = []
        for field in sorted(ds_src["field_path"].astype(str).unique()):
            src = ds_src[ds_src["field_path"].astype(str) == field]
            kept = ds_keep[ds_keep["field"] == field] if not ds_keep.empty else pd.DataFrame()
            excluded = ds_exclusion[ds_exclusion["field"] == field] if not ds_exclusion.empty else pd.DataFrame()
            global_row = registry_df[registry_df["field"].astype(str) == field]
            n_present = int(global_row["n_datasets_present"].iloc[0]) if not global_row.empty else int(not kept.empty)
            ds_registry_rows.append(
                _build_registry_row(
                    field,
                    src,
                    kept,
                    excluded,
                    n_present,
                    n_datasets,
                    keep=not kept.empty,
                )
            )
        ds_registry = pd.DataFrame(ds_registry_rows).sort_values(["keep", "field"], ascending=[False, True])

        exclusion_path = dataset_exclusion_log_path(dataset, tag)
        registry_path = dataset_field_registry_path(dataset, tag)
        ds_exclusion.to_csv(exclusion_path, index=False)
        ds_registry.to_csv(registry_path, index=False)

        payload = active.get(dataset, {"n_patients": 0, "fields": [], "coverage": {}})
        kept_path = dataset_kept_fields_path(dataset, tag)
        kept_path.parent.mkdir(parents=True, exist_ok=True)
        with open(kept_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"✅ exclusion_log : {exclusion_path}  ({len(ds_exclusion)} 行)")
        print(f"✅ field_registry: {registry_path}  ({len(ds_registry)} 行, keep={int(ds_registry['keep'].sum()) if not ds_registry.empty else 0})")
        print(f"✅ kept_fields   : {kept_path}  ({len(payload.get('fields', []))} 字段)")

    if str(getattr(args, "dataset", "all") or "all") == "all":
        summary = {}
        for dataset in datasets:
            payload = active.get(dataset, {"n_patients": 0, "fields": []})
            summary[dataset] = {
                "n_patients": payload.get("n_patients", 0),
                "fields": list(payload.get("fields", [])),
            }
        summary_path = shared_kept_fields_path(tag)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"✅ kept_fields 总表: {summary_path}  ({len(summary)} 个数据集)")

    if args.write_templates:
        from .field_bank import write_field_bank_template_skeleton

        for dataset, payload in active.items():
            src = df[df["dataset"].astype(str) == str(dataset)]
            examples = {}
            wanted = set(payload["fields"])
            for _, row in src.iterrows():
                field = str(row["field_path"])
                if field in wanted:
                    examples[field] = _example_value(row)
            write_field_bank_template_skeleton(
                dataset_name=dataset,
                fields=payload["fields"],
                out_dir=dataset_field_bank_template_dir(dataset, tag),
                examples=examples,
            )
