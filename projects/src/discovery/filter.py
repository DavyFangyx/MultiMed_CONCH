"""R0-R6 field filtering and active Field Bank manifest generation."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from common.paths import DEFAULT_FIELD_BANK_TEMPLATE_DIR, REGISTRY_DIR


R0_SUBSTRINGS = {
    "vital_status",
    "days_to_death",
    "year_of_death",
    "days_to_last_follow_up",
    "days_to_last_known_disease_status",
    "last_known_disease_status",
    "progression_or_recurrence",
    "days_to_recurrence",
    "days_to_progression",
    "treatment_or_therapy",
    "days_to_treatment_start",
    "days_to_treatment_end",
    "treatment_outcome",
    "cause_of_death",
    "days_to_diagnosis",
}
R0_EXACT = {"state"}

R1_EXACT = {
    "submitter_id",
    "case_id",
    "updated_datetime",
    "created_datetime",
    "project_id",
    "disease_type",
    "primary_site",
    "classification_of_tumor",
}

CONTAINER_LEAFS = {
    "demographic",
    "diagnoses",
    "follow_ups",
    "treatments",
    "pathology_details",
    "exposures",
    "family_histories",
    "project",
    "molecular_tests",
    "other_clinical_attributes",
}

POST_BASELINE_LAYERS = {"follow_ups", "other_clinical_attributes"}

R5_DROP_LEAFS = {
    "age_at_index": ("R5_derivable", "keep diagnoses.age_at_diagnosis"),
    "days_to_birth": ("R5_derivable", "keep diagnoses.age_at_diagnosis"),
    "ajcc_pathologic_stage": ("R5_derivable", "keep ajcc_pathologic_t/n/m"),
    "ajcc_staging_system_edition": ("R5_derivable", "not patient-level / not comparable"),
    "year_of_diagnosis": ("R5_derivable", "administrative censoring confounder"),
}


def _leaf_name(field_path: str) -> str:
    return str(field_path).split(".")[-1].replace("[]", "")


def _layer_name(field_path: str) -> str:
    raw = str(field_path)
    if "." not in raw:
        return "case"
    return raw.split(".")[0].replace("[]", "")


def _norm(field_path: str) -> str:
    return str(field_path).replace("[]", "").lower()


def temporal_flag(field_path: str) -> str:
    parts = {p.replace("[]", "") for p in str(field_path).split(".")}
    if parts & POST_BASELINE_LAYERS:
        return "post_baseline"
    return "baseline"


def apply_rules(row: pd.Series, min_coverage: float) -> tuple[str | None, str]:
    """Apply R0-R5 in document order. R2/R6 are markers, not drop rules."""
    field_path = str(row["field_path"])
    leaf = _leaf_name(field_path).lower()
    norm = _norm(field_path)

    # R0: label leakage. Hard exclusion, never skip.
    if leaf in R0_EXACT or any(token in leaf or token in norm for token in R0_SUBSTRINGS):
        return "R0_label_leak", leaf
    if leaf.startswith("days_to_") and leaf != "days_to_birth":
        return "R0_label_leak", leaf

    # R1: administrative / identifier fields.
    if leaf in R1_EXACT or leaf.endswith("_id"):
        return "R1_admin", leaf
    if leaf in CONTAINER_LEAFS:
        return "R1_admin", f"container:{leaf}"

    # R2 is a marker only; see temporal_flag().

    # R3: coverage threshold.
    coverage = float(row.get("coverage") or 0.0)
    if coverage < min_coverage:
        return "R3_coverage", f"{coverage:.6f}<{min_coverage}"

    # R4: degenerate fields.
    n_unique = int(row.get("unique_count") or 0)
    mode_share = float(row.get("mode_share") or 0.0)
    if n_unique < 2:
        return "R4_degenerate", f"n_unique={n_unique}"
    if mode_share > 0.95:
        return "R4_degenerate", f"mode_share={mode_share:.6f}"

    # Extra derivable-field drops kept from the current registry.
    if leaf in R5_DROP_LEAFS:
        rule, note = R5_DROP_LEAFS[leaf]
        return rule, note

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


def _iqr(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(series.quantile(0.75) - series.quantile(0.25))


def run_field_filter(args):
    stats_path = Path(args.stats_csv) if args.stats_csv else REGISTRY_DIR / "field_stats_raw.csv"
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

    exclusion_rows = []
    keep_rows = []
    for _, row in df.iterrows():
        rule, trigger = apply_rules(row, min_coverage=args.min_coverage)
        item = {
            "dataset": row["dataset"],
            "field": row["field_path"],
            "layer": row.get("layer") or _layer_name(row["field_path"]),
            "coverage": float(row.get("coverage") or 0.0),
            "n_unique": int(row.get("unique_count") or 0),
            "mode_share": float(row.get("mode_share") or 0.0),
            "inferred_type": row.get("inferred_type") or "",
            "n_patients": int(row.get("total") or 0),
            "temporal_flag": temporal_flag(row["field_path"]),
        }
        if rule:
            exclusion_rows.append(
                {
                    "dataset": item["dataset"],
                    "field": item["field"],
                    "layer": item["layer"],
                    "rule": rule,
                    "trigger": trigger,
                    "coverage": item["coverage"],
                    "n_unique": item["n_unique"],
                    "mode_share": item["mode_share"],
                    "temporal_flag": item["temporal_flag"],
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
        keep = n_present > 0
        excluded_by = "" if keep else ",".join(sorted(excluded["rule"].unique())) if not excluded.empty else ""
        coverage_series = kept["coverage"] if keep else src["coverage"]
        unique_series = kept["n_unique"] if keep else src["unique_count"]
        mode_series = kept["mode_share"] if keep else src["mode_share"]
        inferred = (
            kept["inferred_type"].mode().iloc[0]
            if keep and not kept["inferred_type"].isna().all()
            else (src["inferred_type"].mode().iloc[0] if not src["inferred_type"].isna().all() else "")
        )
        registry_rows.append(
            {
                "field": field,
                "layer": _layer_name(field),
                "inferred_type": inferred,
                "temporal_flag": temporal_flag(field),
                "portability": _portability(n_present, n_datasets),
                "n_datasets_present": n_present,
                "coverage_median": round(float(coverage_series.median()) if len(coverage_series) else 0.0, 6),
                "coverage_iqr": round(_iqr(coverage_series.astype(float)), 6),
                "n_unique_median": round(float(unique_series.median()) if len(unique_series) else 0.0, 6),
                "mode_share_median": round(float(mode_series.median()) if len(mode_series) else 0.0, 6),
                "excluded_by": excluded_by,
                "keep": keep,
                "note": "R2 marks post_baseline; R6 marks portability only",
            }
        )

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

    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    exclusion_path = REGISTRY_DIR / "exclusion_log.csv"
    registry_path = REGISTRY_DIR / "field_registry.csv"
    active_path = REGISTRY_DIR / "active_fields.json"
    exclusion_df.to_csv(exclusion_path, index=False)
    registry_df.to_csv(registry_path, index=False)
    with open(active_path, "w", encoding="utf-8") as f:
        json.dump(active, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"✅ exclusion_log : {exclusion_path}  ({len(exclusion_df)} 行)")
    print(f"✅ field_registry: {registry_path}  ({len(registry_df)} 行, keep={int(registry_df['keep'].sum())})")
    print(f"✅ active_fields : {active_path}  ({len(active)} 个数据集)")

    if args.write_templates:
        from .field_bank import write_field_bank_template_skeleton

        for dataset, payload in active.items():
            write_field_bank_template_skeleton(
                dataset_name=dataset,
                fields=payload["fields"],
                out_dir=DEFAULT_FIELD_BANK_TEMPLATE_DIR,
            )
