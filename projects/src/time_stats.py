"""Extract per-patient survival time plus t_write / t_record entity times.

Dead   -> last time = demographic.days_to_death
Not dead -> last time = diagnoses[].days_to_last_follow_up,
            else follow_ups[].days_to_follow_up

Only six entities are timed: diagnoses, treatments, pathology_details,
follow_ups, molecular_tests, other_clinical_attributes.
case / demographic / exposures / family_histories are ignored.

t_write  uses each object's updated_datetime (created_datetime ignored).
t_record uses clinical days_* with narrow timepoint_category fallbacks.
See rawdata_stats/TIME_CRITERIA.md.

Outputs in projects/rawdata_stats/{dataset}/time_write and time_record:
  patient_time_stats.csv / patient_time_stats.png
  normalized_update_time.csv / normalized_update_time.png / normalized_update_time_boxplot.png
  sequences/{family}.csv / sequences/{family}.png
  missing/{family}.csv / missing/{family}.png

conda activate conch
cd CONCH-main
python projects/scripts/run_time_stats.py --dataset all
python projects/scripts/run_time_stats.py --dataset TCGA_LIHC
python projects/scripts/run_time_stats.py --self_test
"""

from __future__ import annotations

import argparse
import math
import os
import re
import shutil
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from common.clinical_io import load_clinical_cases
from common.datasets import (
    get_dataset_clinic_files,
    get_dataset_project_ids,
    load_dataset_configs,
    resolve_dataset_names,
)
from common.paths import DEFAULT_DATASETS_CONFIG, DEFAULT_JSON_PATH, TIME_STATS_ROOT

OUTPUT_ROOT = TIME_STATS_ROOT

_MPLCONFIG_DIR = Path("/tmp") / "mplconfig_time_stats"
_MPLCONFIG_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPLCONFIG_DIR))

STALE_OUTPUTS = (
    "all_updated_datetime_distribution.png",
    "updated_datetime_distribution.png",
    "time_stats_summary.csv",
    "time_stats_summary_all.csv",
    "patient_normalized_update_time.csv",
    "field_normalized_update_summary.csv",
    "field_normalized_update_summary_all.csv",
    "normalized_update_time_curves.png",
    "normalized_update_time_by_field.png",
    "ground_truth_time_distribution.png",
    "ground_truth_time_distribution_all.png",
)

TIME_FAMILIES = [
    "diagnoses",
    "diagnoses_treatments",
    "diagnoses_pathology_details",
    "follow_ups",
    "follow_ups_molecular_tests",
    "follow_ups_other_clinical_attributes",
]

FAMILY_PATHS = {
    "diagnoses": "diagnoses[]",
    "diagnoses_treatments": "diagnoses[].treatments[]",
    "diagnoses_pathology_details": "diagnoses[].pathology_details[]",
    "follow_ups": "follow_ups[]",
    "follow_ups_molecular_tests": "follow_ups[].molecular_tests[]",
    "follow_ups_other_clinical_attributes": "follow_ups[].other_clinical_attributes[]",
}

TREATMENT_BASELINE_TIMEPOINTS = frozenset(
    {
        "prior to diagnosis",
        "preoperative",
        "prior to procurement",
        "pretreatment",
        "pre-treatment",
    }
)
PATHOLOGY_BASELINE_TIMEPOINTS = frozenset(
    {
        "initial diagnosis",
        "prior to diagnosis",
    }
)

WRITE_COL_RE = re.compile(r"^(.*)_updated(\d+)$")
RECORD_COL_RE = re.compile(r"^(.*)_record(\d+)$")
SEQUENCE_ID_COLS = ["dataset", "submitter_id", "case_id"]
WRITE_KIND = "write"
RECORD_KIND = "record"


def _iter_dict_items(value):
    if not isinstance(value, list):
        return
    for item in value:
        if isinstance(item, dict):
            yield item


def _is_non_empty(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _to_float(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num):
        return None
    return num


def _parse_datetime(value):
    if not _is_non_empty(value):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


def _normalize_vital_status(value) -> str:
    return str(value or "").strip()


def _is_alive(status: str) -> bool:
    return status.lower() == "alive"


def _is_dead(status: str) -> bool:
    return status.lower() == "dead"


def _max_numeric(values) -> float | None:
    nums = [n for n in (_to_float(v) for v in values) if n is not None]
    if not nums:
        return None
    return max(nums)


def _normalize_timepoint(value) -> str:
    return str(value or "").strip().lower()


def _timepoint_in(value, vocab: frozenset[str]) -> bool:
    return _normalize_timepoint(value) in vocab


def _collect_days_to_last_follow_up(case: dict) -> tuple[float | None, str]:
    diagnoses = case.get("diagnoses") if isinstance(case.get("diagnoses"), list) else []
    last_fu = _max_numeric(
        item.get("days_to_last_follow_up")
        for item in diagnoses
        if isinstance(item, dict)
    )
    if last_fu is not None:
        return last_fu, "diagnoses.days_to_last_follow_up"

    follow_ups = case.get("follow_ups") if isinstance(case.get("follow_ups"), list) else []
    follow_fu = _max_numeric(
        item.get("days_to_follow_up")
        for item in follow_ups
        if isinstance(item, dict)
    )
    if follow_fu is not None:
        return follow_fu, "follow_ups.days_to_follow_up"
    return None, ""


def _year_of_diagnosis(case: dict) -> int | None:
    diagnoses = case.get("diagnoses") if isinstance(case.get("diagnoses"), list) else []
    primary_years = []
    years = []
    for item in diagnoses:
        if not isinstance(item, dict):
            continue
        try:
            year = int(item.get("year_of_diagnosis"))
        except (TypeError, ValueError):
            continue
        years.append(year)
        is_primary = str(item.get("diagnosis_is_primary_disease") or "").lower() == "true"
        is_tumor_primary = str(item.get("classification_of_tumor") or "").lower() == "primary"
        if is_primary or is_tumor_primary:
            primary_years.append(year)
    if primary_years:
        return min(primary_years)
    if years:
        return min(years)
    return None


def _write_value(obj: dict):
    raw = obj.get("updated_datetime")
    dt = _parse_datetime(raw)
    if dt is None:
        return None, ""
    text = str(raw).strip() if _is_non_empty(raw) else _format_datetime(dt)
    return dt, text


def _record_days_diagnosis(obj: dict, parent_days=None):
    return _to_float(obj.get("days_to_diagnosis"))


def _record_days_treatment(obj: dict, parent_days):
    primary = _to_float(obj.get("days_to_treatment_start"))
    if primary is not None:
        return primary
    if _timepoint_in(obj.get("timepoint_category"), TREATMENT_BASELINE_TIMEPOINTS):
        return parent_days
    return None


def _record_days_pathology(obj: dict, parent_days):
    primary = _to_float(obj.get("days_to_pathology_detail"))
    if primary is not None:
        return primary
    if _timepoint_in(obj.get("timepoint_category"), PATHOLOGY_BASELINE_TIMEPOINTS):
        return parent_days
    return None


def _record_days_follow_up(obj: dict, parent_days=None):
    return _to_float(obj.get("days_to_follow_up"))


def _record_days_molecular(obj: dict, parent_days):
    primary = _to_float(obj.get("days_to_test"))
    if primary is not None:
        return primary
    return parent_days


def _record_days_other(obj: dict, parent_days):
    comorbidity = _to_float(obj.get("days_to_comorbidity"))
    if comorbidity is not None:
        return comorbidity
    risk = _to_float(obj.get("days_to_risk_factor"))
    if risk is not None:
        return risk
    return parent_days


def _make_slot(obj: dict, record_days) -> dict:
    dt, text = _write_value(obj)
    return {
        "present": True,
        "write_dt": dt,
        "write_text": text,
        "record_days": record_days,
    }

def _empty_slots() -> OrderedDict:
    return OrderedDict((family, []) for family in TIME_FAMILIES)


def _collect_entity_slots(case: dict) -> OrderedDict:
    slots = _empty_slots()

    for diagnosis in _iter_dict_items(case.get("diagnoses")):
        diagnosis_days = _record_days_diagnosis(diagnosis)
        slots["diagnoses"].append(_make_slot(diagnosis, diagnosis_days))
        for treatment in _iter_dict_items(diagnosis.get("treatments")):
            slots["diagnoses_treatments"].append(
                _make_slot(treatment, _record_days_treatment(treatment, diagnosis_days))
            )
        for pathology in _iter_dict_items(diagnosis.get("pathology_details")):
            slots["diagnoses_pathology_details"].append(
                _make_slot(pathology, _record_days_pathology(pathology, diagnosis_days))
            )

    for follow_up in _iter_dict_items(case.get("follow_ups")):
        follow_days = _record_days_follow_up(follow_up)
        slots["follow_ups"].append(_make_slot(follow_up, follow_days))
        for molecular in _iter_dict_items(follow_up.get("molecular_tests")):
            slots["follow_ups_molecular_tests"].append(
                _make_slot(molecular, _record_days_molecular(molecular, follow_days))
            )
        for other in _iter_dict_items(follow_up.get("other_clinical_attributes")):
            slots["follow_ups_other_clinical_attributes"].append(
                _make_slot(other, _record_days_other(other, follow_days))
            )
    return slots


def extract_patient_time_record(case: dict, dataset_name: str | None = None) -> dict:
    demographic = case.get("demographic") if isinstance(case.get("demographic"), dict) else {}
    vital_status = _normalize_vital_status(demographic.get("vital_status"))
    days_to_death = _to_float(demographic.get("days_to_death"))
    days_to_last_follow_up, last_fu_source = _collect_days_to_last_follow_up(case)

    if _is_dead(vital_status):
        ground_truth_time = days_to_death
        ground_truth_source = "demographic.days_to_death"
        event = 1
    else:
        ground_truth_time = days_to_last_follow_up
        ground_truth_source = last_fu_source or "diagnoses.days_to_last_follow_up"
        event = 0 if _is_alive(vital_status) else None

    record = OrderedDict(
        [
            ("dataset", dataset_name or ""),
            ("submitter_id", str(case.get("submitter_id") or "").strip()),
            ("case_id", str(case.get("case_id") or "").strip()),
            ("project_id", str((case.get("project") or {}).get("project_id") or "").strip()),
            ("vital_status", vital_status),
            ("lost_to_followup", case.get("lost_to_followup")),
            ("event", event),
            ("ground_truth_time", ground_truth_time),
            ("ground_truth_source", ground_truth_source),
            ("days_to_last_follow_up", days_to_last_follow_up),
            ("days_to_death", days_to_death),
            ("year_of_diagnosis", _year_of_diagnosis(case)),
        ]
    )
    record["_slots"] = _collect_entity_slots(case)
    return record


def _slot_column(family: str, index: int, kind: str) -> str:
    suffix = "updated" if kind == WRITE_KIND else "record"
    return f"{family}_{suffix}{index}"


def _expand_kind_columns(records: list[dict], kind: str) -> list[dict]:
    max_lens = OrderedDict((family, 0) for family in TIME_FAMILIES)
    for record in records:
        slots = record.get("_slots") or {}
        for family in TIME_FAMILIES:
            max_lens[family] = max(max_lens[family], len(slots.get(family) or []))

    rows = []
    for record in records:
        row = OrderedDict((k, v) for k, v in record.items() if k != "_slots")
        slots = record.get("_slots") or {}
        for family in TIME_FAMILIES:
            n_values = max_lens[family]
            values = slots.get(family) or []
            for i in range(1, n_values + 1):
                col = _slot_column(family, i, kind)
                if i - 1 >= len(values):
                    row[col] = ""
                    continue
                slot = values[i - 1]
                if kind == WRITE_KIND:
                    row[col] = slot.get("write_text") or ""
                else:
                    days = slot.get("record_days")
                    row[col] = "" if days is None else days
        rows.append(row)
    return rows


def build_patient_time_frame(cases: list, dataset_name: str | None = None, kind: str = WRITE_KIND) -> pd.DataFrame:
    records = [extract_patient_time_record(case, dataset_name=dataset_name) for case in cases]
    rows = _expand_kind_columns(records, kind)
    return pd.DataFrame(rows)


def _slot_re(kind: str):
    return WRITE_COL_RE if kind == WRITE_KIND else RECORD_COL_RE


def _is_slot_column(col: str, kind: str) -> bool:
    return bool(_slot_re(kind).match(col))


def _field_family(col: str, kind: str) -> str:
    match = _slot_re(kind).match(col)
    if match:
        return match.group(1)
    return col


def _slot_index(col: str, kind: str) -> int:
    match = _slot_re(kind).match(col)
    if match:
        return int(match.group(2))
    return 0


def _slot_columns(df: pd.DataFrame, kind: str) -> list[str]:
    return [c for c in df.columns if _is_slot_column(c, kind)]


def _ordered_fields(fields: list[str]) -> list[str]:
    known = [name for name in TIME_FAMILIES if name in fields]
    extra = sorted(name for name in fields if name not in known)
    return known + extra


def _sequence_families(df: pd.DataFrame, kind: str) -> OrderedDict:
    families: OrderedDict[str, list[str]] = OrderedDict()
    for col in _ordered_slot_columns(df, kind):
        family = _field_family(col, kind)
        families.setdefault(family, []).append(col)
    return families


def _ordered_slot_columns(df: pd.DataFrame, kind: str) -> list[str]:
    cols = _slot_columns(df, kind)
    families = _ordered_fields(list(dict.fromkeys(_field_family(c, kind) for c in cols)))
    grouped = {family: [] for family in families}
    extra = []
    for col in cols:
        family = _field_family(col, kind)
        if family in grouped:
            grouped[family].append(col)
        else:
            extra.append(col)
    ordered = []
    for family in families:
        ordered.extend(sorted(grouped[family], key=lambda name: _slot_index(name, kind)))
    ordered.extend(extra)
    return ordered

def _reset_subdir(output_dir: Path, name: str) -> Path:
    path = Path(output_dir) / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _remove_legacy_time_dir(dataset_dir: Path) -> None:
    legacy = Path(dataset_dir) / "time"
    if legacy.exists():
        shutil.rmtree(legacy)


def write_sequence_tables(
    df: pd.DataFrame,
    output_dir: Path,
    id_cols: list[str],
    kind: str,
) -> list[Path]:
    if df.empty:
        return []
    keep_ids = [c for c in id_cols if c in df.columns]
    written = []
    for family, cols in _sequence_families(df, kind).items():
        sub = df.loc[:, keep_ids + cols].copy()
        path = Path(output_dir) / f"{family}.csv"
        sub.to_csv(path, index=False)
        written.append(path)
    return written


def _days_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 86400.0


def _last_time_fields(src) -> tuple[float | None, str]:
    vital_status = _normalize_vital_status(src.get("vital_status"))
    if _is_dead(vital_status):
        return _to_float(src.get("days_to_death")), "demographic.days_to_death"
    last_days = _to_float(src.get("days_to_last_follow_up"))
    last_source = str(src.get("ground_truth_source") or "diagnoses.days_to_last_follow_up")
    return last_days, last_source


def build_normalized_write_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Keep every submission slot. 1 = last_time_days; values may exceed 1."""
    if df.empty:
        return pd.DataFrame()

    update_cols = _ordered_slot_columns(df, WRITE_KIND)
    rows = []
    for _, src in df.iterrows():
        parsed = {}
        all_times = []
        for col in update_cols:
            dt = _parse_datetime(src.get(col))
            if dt is None:
                continue
            parsed[col] = dt
            all_times.append(dt)
        if not all_times:
            continue

        last_days, last_source = _last_time_fields(src)
        t_min = min(all_times)
        t_max = max(all_times)
        row = OrderedDict(
            [
                ("dataset", src.get("dataset", "")),
                ("submitter_id", src.get("submitter_id", "")),
                ("case_id", src.get("case_id", "")),
                ("vital_status", _normalize_vital_status(src.get("vital_status"))),
                ("last_time_days", last_days),
                ("last_time_source", last_source),
                ("first_updated_datetime", _format_datetime(t_min)),
                ("last_updated_datetime", _format_datetime(t_max)),
                ("n_submissions", len(parsed)),
            ]
        )
        for col in update_cols:
            dt = parsed.get(col)
            if dt is None or last_days in (None, 0):
                row[col] = ""
                continue
            row[col] = round(_days_between(t_min, dt) / last_days, 6)
        rows.append(row)
    return pd.DataFrame(rows)


def build_normalized_record_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    record_cols = _ordered_slot_columns(df, RECORD_KIND)
    rows = []
    for _, src in df.iterrows():
        parsed = {}
        for col in record_cols:
            days = _to_float(src.get(col))
            if days is None:
                continue
            parsed[col] = days
        if not parsed:
            continue

        last_days, last_source = _last_time_fields(src)
        row = OrderedDict(
            [
                ("dataset", src.get("dataset", "")),
                ("submitter_id", src.get("submitter_id", "")),
                ("case_id", src.get("case_id", "")),
                ("vital_status", _normalize_vital_status(src.get("vital_status"))),
                ("last_time_days", last_days),
                ("last_time_source", last_source),
                ("n_records", len(parsed)),
            ]
        )
        for col in record_cols:
            days = parsed.get(col)
            if days is None or last_days in (None, 0):
                row[col] = ""
                continue
            row[col] = round(days / last_days, 6)
        rows.append(row)
    return pd.DataFrame(rows)


def _slot_has_time(slot: dict, kind: str) -> bool:
    if kind == WRITE_KIND:
        return slot.get("write_dt") is not None
    return slot.get("record_days") is not None


def _slot_path(family: str, index: int) -> str:
    base = FAMILY_PATHS.get(family, family)
    if base.endswith("[]"):
        return f"{base[:-2]}[{index}]"
    return f"{family}[{index}]"


def build_missing_tables(records: list[dict], kind: str) -> OrderedDict:
    max_lens = OrderedDict((family, 0) for family in TIME_FAMILIES)
    for record in records:
        slots = record.get("_slots") or {}
        for family in TIME_FAMILIES:
            max_lens[family] = max(max_lens[family], len(slots.get(family) or []))

    tables: OrderedDict[str, pd.DataFrame] = OrderedDict()
    for family in TIME_FAMILIES:
        n_slots = max_lens[family]
        if n_slots == 0:
            continue
        rows = []
        for idx in range(1, n_slots + 1):
            present = 0
            covered = 0
            for record in records:
                values = (record.get("_slots") or {}).get(family) or []
                if idx > len(values):
                    continue
                present += 1
                if _slot_has_time(values[idx - 1], kind):
                    covered += 1
            rows.append(
                OrderedDict(
                    [
                        ("slot", idx),
                        ("path", _slot_path(family, idx)),
                        ("covered", covered),
                        ("present", present),
                        ("excluded", present - covered),
                        ("ratio", f"{covered}/{present}"),
                    ]
                )
            )
        tables[family] = pd.DataFrame(rows)
    return tables

def _setup_matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def plot_patient_time_stats(df: pd.DataFrame, output_dir: Path, dataset_name: str) -> Path:
    plt = _setup_matplotlib()
    output_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 5))
    plotted = False
    if not df.empty and "ground_truth_time" in df.columns:
        vital = df["vital_status"].fillna("").astype(str)
        colors = {"Alive": "#4C78A8", "Dead": "#E45756"}
        for status in ("Alive", "Dead"):
            vals = pd.to_numeric(
                df.loc[vital.str.lower() == status.lower(), "ground_truth_time"],
                errors="coerce",
            ).dropna()
            if vals.empty:
                continue
            ax.hist(vals, bins=30, alpha=0.65, label=f"{status} (n={len(vals)})", color=colors[status])
            plotted = True
        other = pd.to_numeric(
            df.loc[~vital.str.lower().isin({"alive", "dead"}), "ground_truth_time"],
            errors="coerce",
        ).dropna()
        if not other.empty:
            ax.hist(other, bins=30, alpha=0.5, label=f"Other (n={len(other)})", color="#72B7B2")
            plotted = True
    if plotted:
        ax.set_xlabel("Ground-truth time (days from index)")
        ax.set_ylabel("Number of patients")
        ax.set_title(f"{dataset_name} ground-truth time")
        ax.legend()
    else:
        ax.text(0.5, 0.5, "No ground-truth time", ha="center", va="center")
        ax.set_axis_off()
    fig.tight_layout()
    path = output_dir / "patient_time_stats.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _column_colors(plt, columns: list[str]) -> dict[str, tuple]:
    n = max(len(columns), 1)
    cmap = plt.get_cmap("tab20" if n <= 20 else "hsv")
    if n == 1:
        return {columns[0]: cmap(0.0)}
    return {col: cmap(i / max(n - 1, 1)) for i, col in enumerate(columns)}


def _apply_decade_yaxis(ax, values) -> None:
    import matplotlib.ticker as ticker
    import numpy as np

    nums = [float(v) for v in values if v is not None and np.isfinite(v)]
    positive = [v for v in nums if v > 0]
    ticks = [1.0, 10.0, 100.0, 1000.0]
    if positive:
        data_max = max(positive)
        while ticks[-1] < data_max:
            ticks.append(ticks[-1] * 10.0)
    y_max = ticks[-1]
    y_min = 0.0
    if nums:
        y_min = min(0.0, min(nums))
    ax.set_yscale("symlog", linthresh=1.0, linscale=0.6, base=10)
    ax.set_ylim(y_min, y_max)
    ax.set_yticks([0.0] + ticks)
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%g"))
    ax.axhline(1.0, color="#444444", linestyle="--", linewidth=1.2, alpha=0.95, xmin=0.0, xmax=1.0)
    ax.set_ylabel("Normalized update time (x10; 1 = clinical end)")


def plot_normalized_update_time(
    wide: pd.DataFrame,
    output_dir: Path,
    dataset_name: str,
    kind: str,
) -> Path | None:
    if wide.empty:
        return None

    plt = _setup_matplotlib()
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_df = wide.copy()
    sort_cols = [c for c in ("last_updated_datetime", "submitter_id") if c in plot_df.columns]
    if sort_cols:
        plot_df = plot_df.sort_values(sort_cols).reset_index(drop=True)
    else:
        plot_df = plot_df.sort_values("submitter_id").reset_index(drop=True)
    plot_df["patient_index"] = range(1, len(plot_df) + 1)

    plotted_cols = []
    for col in _ordered_slot_columns(plot_df, kind):
        y = pd.to_numeric(plot_df[col], errors="coerce")
        if y.notna().sum() == 0:
            continue
        plotted_cols.append(col)
    if not plotted_cols:
        return None

    colors = _column_colors(plt, plotted_cols)
    n = len(plot_df)
    fig_w = max(10, min(18, 8 + n / 80))
    fig_h = 5.5 + min(6, 0.18 * len(plotted_cols))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    x = plot_df["patient_index"].to_numpy()
    for col in plotted_cols:
        y = pd.to_numeric(plot_df[col], errors="coerce")
        ax.plot(x, y, color=colors[col], linewidth=1.0, alpha=0.9, label=col)

    ys = []
    for col in plotted_cols:
        ys.extend(pd.to_numeric(plot_df[col], errors="coerce").dropna().tolist())
    _apply_decade_yaxis(ax, ys)
    ax.set_xlim(1, max(n, 1))
    ax.set_xlabel("Patients")
    ax.set_title(f"{dataset_name} field update time normalized by clinical end")
    ncol = 1 if len(plotted_cols) <= 18 else 2
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=7, frameon=False, ncol=ncol)
    if n > 40:
        ax.set_xticks([1, n])
        ax.set_xticklabels(["1", str(n)])
    fig.tight_layout()
    path = output_dir / "normalized_update_time.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_normalized_update_time_boxplot(
    wide: pd.DataFrame,
    output_dir: Path,
    dataset_name: str,
    kind: str,
) -> Path | None:
    if wide.empty:
        return None

    plt = _setup_matplotlib()
    output_dir.mkdir(parents=True, exist_ok=True)
    data = []
    labels = []
    for col in _ordered_slot_columns(wide, kind):
        vals = pd.to_numeric(wide[col], errors="coerce").dropna().tolist()
        if not vals:
            continue
        data.append(vals)
        labels.append(col)
    if not data:
        return None

    fig_w = max(10, min(24, 1.15 * len(labels) + 3))
    fig, ax = plt.subplots(figsize=(fig_w, 6))
    ax.boxplot(
        data,
        tick_labels=labels,
        showfliers=True,
        flierprops={
            "marker": "o",
            "markersize": 4.5,
            "markerfacecolor": "#222222",
            "markeredgecolor": "#222222",
            "linestyle": "none",
            "alpha": 0.85,
        },
    )
    ys = [v for vals in data for v in vals]
    _apply_decade_yaxis(ax, ys)
    ax.plot([], [], "o", color="#222222", markersize=4.5, label="outlier")
    ax.legend(loc="upper right", frameon=False, fontsize=9)
    ax.set_title(f"{dataset_name} each update slot vs clinical end")
    ax.tick_params(axis="x", labelrotation=45)
    for label in ax.get_xticklabels():
        label.set_ha("right")
        label.set_fontsize(8)
    fig.tight_layout()
    path = output_dir / "normalized_update_time_boxplot.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path

def _subplot_grid(n_axes: int) -> tuple[int, int]:
    if n_axes <= 1:
        return 1, 1
    if n_axes <= 3:
        return 1, n_axes
    if n_axes <= 12:
        n_cols = 3
    else:
        n_cols = 4
    n_rows = math.ceil(n_axes / n_cols)
    return n_rows, n_cols


def plot_sequence_family_times(
    wide: pd.DataFrame,
    output_dir: Path,
    dataset_name: str,
    kind: str,
) -> list[Path]:
    """One PNG per sequence family. Each slot is a subplot; x = sample index."""
    if wide.empty:
        return []

    plt = _setup_matplotlib()
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_df = wide.reset_index(drop=True).copy()
    plot_df["patient_index"] = range(1, len(plot_df) + 1)
    x = plot_df["patient_index"].to_numpy()
    n_patients = len(plot_df)
    written = []
    suffix = "updated" if kind == WRITE_KIND else "record"

    for family, cols in _sequence_families(plot_df, kind).items():
        plotted_cols = []
        ys_all = []
        for col in cols:
            y = pd.to_numeric(plot_df[col], errors="coerce")
            if y.notna().sum() == 0:
                continue
            plotted_cols.append(col)
            ys_all.extend(y.dropna().tolist())
        if not plotted_cols:
            continue

        n_rows, n_cols = _subplot_grid(len(plotted_cols))
        fig_w = max(8.0, 4.2 * n_cols)
        fig_h = max(3.2, 2.4 * n_rows)
        fig, axes = plt.subplots(
            n_rows,
            n_cols,
            figsize=(fig_w, fig_h),
            sharex=True,
            sharey=True,
            squeeze=False,
        )
        flat = axes.ravel()
        data_max = max(ys_all) if ys_all else 1.0
        use_decade = data_max > 2.0
        for i, col in enumerate(plotted_cols):
            ax = flat[i]
            y = pd.to_numeric(plot_df[col], errors="coerce")
            ax.plot(x, y, color="#4C78A8", linewidth=0.9, alpha=0.9)
            slot = col.rsplit(f"_{suffix}", 1)[-1]
            ax.set_title(f"{suffix}{slot}", fontsize=9)
            ax.axhline(1.0, color="#444444", linestyle="--", linewidth=0.9, alpha=0.8)
            ax.set_xlim(1, max(n_patients, 1))
            if use_decade:
                _apply_decade_yaxis(ax, ys_all)
            else:
                ax.set_ylim(min(0.0, min(ys_all)), max(1.05, data_max * 1.08))
            if n_patients > 40:
                ax.set_xticks([1, n_patients])
                ax.set_xticklabels(["1", str(n_patients)])
        for j in range(len(plotted_cols), len(flat)):
            flat[j].set_visible(False)
        fig.suptitle(
            f"{dataset_name} {family}: normalized update time by sample",
            fontsize=11,
        )
        fig.supxlabel("Patients")
        fig.supylabel("Normalized update time (1 = clinical end)")
        fig.tight_layout()
        path = Path(output_dir) / f"{family}.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        written.append(path)
    return written


def plot_missing_family(df: pd.DataFrame, output_dir: Path, family: str, dataset_name: str) -> Path | None:
    if df.empty:
        return None
    plt = _setup_matplotlib()
    output_dir.mkdir(parents=True, exist_ok=True)
    labels = [str(v) for v in df["path"].tolist()]
    covered = pd.to_numeric(df["covered"], errors="coerce").fillna(0).tolist()
    present = pd.to_numeric(df["present"], errors="coerce").fillna(0).tolist()
    x = range(len(labels))
    fig_w = max(8.0, min(22.0, 1.2 * len(labels) + 3))
    fig, ax = plt.subplots(figsize=(fig_w, 5.2))
    ax.bar(x, present, color="#D9D9D9", label="present")
    ax.bar(x, covered, color="#4C78A8", label="timed")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Patients")
    ax.set_title(f"{dataset_name} {family} slot coverage")
    ax.legend(frameon=False)
    fig.tight_layout()
    path = Path(output_dir) / f"{family}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_patient_time_stats_all(dataset_frames: list[tuple[str, pd.DataFrame]], output_dir: Path) -> Path | None:
    if len(dataset_frames) < 2:
        return None

    plt = _setup_matplotlib()
    output_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 5))
    plotted = False
    for name, df in dataset_frames:
        vals = pd.to_numeric(df.get("ground_truth_time", pd.Series(dtype=float)), errors="coerce").dropna()
        if vals.empty:
            continue
        ax.hist(vals, bins=30, alpha=0.45, label=f"{name} (n={len(vals)})")
        plotted = True
    if not plotted:
        plt.close(fig)
        return None
    ax.set_xlabel("Ground-truth time (days from index)")
    ax.set_ylabel("Number of patients")
    ax.set_title("Ground-truth time by dataset")
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = output_dir / "patient_time_stats_all.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _cleanup_stale_outputs(output_dir: Path) -> None:
    for name in STALE_OUTPUTS:
        path = output_dir / name
        if path.exists():
            path.unlink()

def _write_kind_outputs(
    records: list[dict],
    output_dir: Path,
    dataset_name: str,
    kind: str,
) -> pd.DataFrame:
    output_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_stale_outputs(output_dir)
    rows = _expand_kind_columns(records, kind)
    df = pd.DataFrame(rows)

    csv_path = output_dir / "patient_time_stats.csv"
    df.to_csv(csv_path, index=False)
    png_path = plot_patient_time_stats(df, output_dir, dataset_name)
    print(f"  {kind} patient_time_stats: {csv_path}")
    print(f"  {kind} patient_time_stats: {png_path}")

    seq_dir = _reset_subdir(output_dir, "sequences")
    for path in write_sequence_tables(df, seq_dir, SEQUENCE_ID_COLS, kind):
        print(f"  {kind} sequence table: {path}")

    if kind == WRITE_KIND:
        wide = build_normalized_write_frame(df)
    else:
        wide = build_normalized_record_frame(df)
    if not wide.empty:
        norm_csv = output_dir / "normalized_update_time.csv"
        wide.to_csv(norm_csv, index=False)
        norm_png = plot_normalized_update_time(wide, output_dir, dataset_name, kind)
        box_png = plot_normalized_update_time_boxplot(wide, output_dir, dataset_name, kind)
        print(f"  {kind} normalized_update_time: {norm_csv}")
        if norm_png is not None:
            print(f"  {kind} normalized_update_time: {norm_png}")
        if box_png is not None:
            print(f"  {kind} normalized_update_time: {box_png}")
        for path in plot_sequence_family_times(wide, seq_dir, dataset_name, kind):
            print(f"  {kind} sequence plot: {path}")

    miss_dir = _reset_subdir(output_dir, "missing")
    for family, miss_df in build_missing_tables(records, kind).items():
        miss_csv = miss_dir / f"{family}.csv"
        miss_df.to_csv(miss_csv, index=False)
        print(f"  {kind} missing table: {miss_csv}")
        miss_png = plot_missing_family(miss_df, miss_dir, family, dataset_name)
        if miss_png is not None:
            print(f"  {kind} missing plot: {miss_png}")
    return df


def analyze_dataset_times(
    json_paths,
    dataset_name: str,
    output_dir: Path,
    project_ids: list | None = None,
) -> pd.DataFrame:
    print("######## Dataset: {} ########".format(dataset_name))
    cases = load_clinical_cases(json_paths, project_ids=project_ids)
    records = [extract_patient_time_record(case, dataset_name=dataset_name) for case in cases]

    dataset_dir = Path(output_dir)
    _remove_legacy_time_dir(dataset_dir)
    write_df = _write_kind_outputs(records, dataset_dir / "time_write", dataset_name, WRITE_KIND)
    _write_kind_outputs(records, dataset_dir / "time_record", dataset_name, RECORD_KIND)
    return write_df

def _synthetic_cases() -> list[dict]:
    alive = {
        "submitter_id": "TCGA-AA-0001",
        "case_id": "uuid-1",
        "lost_to_followup": "No",
        "updated_datetime": "2024-01-01T00:00:00-06:00",
        "project": {"project_id": "TCGA-TEST"},
        "demographic": {
            "vital_status": "Alive",
            "days_to_death": None,
            "updated_datetime": "2024-02-01T00:00:00-06:00",
        },
        "diagnoses": [
            {
                "days_to_diagnosis": 0,
                "days_to_last_follow_up": 120,
                "year_of_diagnosis": 2023,
                "updated_datetime": "2024-03-01T00:00:00-06:00",
                "treatments": [
                    {
                        "days_to_treatment_start": 10,
                        "updated_datetime": "2024-03-02T00:00:00-06:00",
                    },
                    {
                        "timepoint_category": "Preoperative",
                        "updated_datetime": "2024-03-03T00:00:00-06:00",
                    },
                    {
                        "timepoint_category": "Postoperative",
                    },
                ],
                "pathology_details": [
                    {
                        "days_to_pathology_detail": 2,
                        "updated_datetime": "2024-03-04T00:00:00-06:00",
                    },
                    {
                        "timepoint_category": "Initial Diagnosis",
                    },
                ],
            }
        ],
        "follow_ups": [
            {
                "days_to_follow_up": 80,
                "updated_datetime": "2024-04-01T00:00:00-06:00",
                "molecular_tests": [
                    {"days_to_test": 70, "updated_datetime": "2024-04-02T00:00:00-06:00"},
                    {"updated_datetime": "2024-04-03T00:00:00-06:00"},
                ],
                "other_clinical_attributes": [
                    {
                        "days_to_comorbidity": 75,
                        "days_to_risk_factor": 90,
                        "updated_datetime": "2024-04-04T00:00:00-06:00",
                    },
                    {
                        "updated_datetime": "2024-04-05T00:00:00-06:00",
                    },
                ],
            },
            {
                "updated_datetime": "2024-08-01T00:00:00-06:00",
            },
        ],
        "exposures": [{"updated_datetime": "2024-07-01T00:00:00-06:00"}],
        "family_histories": [{"updated_datetime": "2024-08-01T00:00:00-06:00"}],
    }
    dead = {
        "submitter_id": "TCGA-AA-0002",
        "case_id": "uuid-2",
        "lost_to_followup": "Yes",
        "updated_datetime": "2024-05-01T00:00:00-06:00",
        "project": {"project_id": "TCGA-TEST"},
        "demographic": {
            "vital_status": "Dead",
            "days_to_death": 45,
            "updated_datetime": "2024-06-01T00:00:00-06:00",
        },
        "diagnoses": [
            {
                "days_to_diagnosis": 0,
                "days_to_last_follow_up": 40,
                "year_of_diagnosis": 2024,
                "updated_datetime": "2024-07-01T00:00:00-06:00",
                "treatments": [
                    {"days_to_treatment_start": 5, "updated_datetime": "2024-07-02T00:00:00-06:00"},
                ],
            }
        ],
        "follow_ups": [
            {
                "days_to_follow_up": 40,
                "updated_datetime": "2024-09-01T00:00:00-06:00",
                "molecular_tests": [{}],
            },
        ],
    }
    return [alive, dead]


def _assert_no_ignored_columns(df: pd.DataFrame) -> None:
    joined = " ".join(str(c) for c in df.columns)
    for token in ("exposures", "family_histories", "demographic_updated", "updated_datetime"):
        assert token not in joined


def run_self_test() -> None:
    cases = _synthetic_cases()
    records = [extract_patient_time_record(case, dataset_name="synthetic") for case in cases]
    write_df = pd.DataFrame(_expand_kind_columns(records, WRITE_KIND))
    record_df = pd.DataFrame(_expand_kind_columns(records, RECORD_KIND))

    assert list(write_df["submitter_id"]) == ["TCGA-AA-0001", "TCGA-AA-0002"]
    assert write_df.loc[0, "ground_truth_time"] == 120
    assert write_df.loc[0, "event"] == 0
    assert write_df.loc[1, "ground_truth_time"] == 45
    assert write_df.loc[1, "event"] == 1
    assert write_df.loc[1, "lost_to_followup"] == "Yes"
    _assert_no_ignored_columns(write_df)
    _assert_no_ignored_columns(record_df)
    assert "diagnoses_updated1" in write_df.columns
    assert "diagnoses_treatments_updated1" in write_df.columns
    assert "diagnoses_treatments_updated2" in write_df.columns
    assert "follow_ups_updated1" in write_df.columns
    assert "follow_ups_updated2" in write_df.columns
    assert str(write_df.loc[0, "diagnoses_treatments_updated2"]).startswith("2024-03-03")
    treat3 = write_df.loc[0, "diagnoses_treatments_updated3"]
    assert treat3 == "" or pd.isna(treat3)
    follow2 = write_df.loc[1, "follow_ups_updated2"]
    assert follow2 == "" or pd.isna(follow2)

    assert record_df.loc[0, "diagnoses_record1"] == 0
    assert record_df.loc[0, "diagnoses_treatments_record1"] == 10
    assert record_df.loc[0, "diagnoses_treatments_record2"] == 0
    treat3_days = record_df.loc[0, "diagnoses_treatments_record3"]
    assert treat3_days == "" or pd.isna(treat3_days)
    assert record_df.loc[0, "diagnoses_pathology_details_record1"] == 2
    assert record_df.loc[0, "diagnoses_pathology_details_record2"] == 0
    assert record_df.loc[0, "follow_ups_record1"] == 80
    follow2_days = record_df.loc[0, "follow_ups_record2"]
    assert follow2_days == "" or pd.isna(follow2_days)
    assert record_df.loc[0, "follow_ups_molecular_tests_record1"] == 70
    assert record_df.loc[0, "follow_ups_molecular_tests_record2"] == 80
    assert record_df.loc[0, "follow_ups_other_clinical_attributes_record1"] == 75
    assert record_df.loc[0, "follow_ups_other_clinical_attributes_record2"] == 80

    wide = build_normalized_write_frame(write_df)
    assert not wide.empty
    assert float(wide.loc[0, "last_time_days"]) == 120
    assert wide.loc[0, "last_time_source"] == "diagnoses.days_to_last_follow_up"
    assert wide.loc[1, "last_time_source"] == "demographic.days_to_death"
    assert float(wide.loc[0, "follow_ups_updated1"]) < float(wide.loc[0, "follow_ups_updated2"])
    assert float(wide.loc[0, "diagnoses_treatments_updated1"]) < float(wide.loc[0, "diagnoses_treatments_updated2"])
    assert float(wide.loc[0, "follow_ups_updated2"]) > 1.0
    assert float(wide.loc[1, "follow_ups_updated1"]) > 1.0

    rec_wide = build_normalized_record_frame(record_df)
    assert float(rec_wide.loc[0, "diagnoses_treatments_record1"]) == round(10 / 120, 6)
    assert float(rec_wide.loc[0, "follow_ups_other_clinical_attributes_record1"]) == round(75 / 120, 6)
    assert float(rec_wide.loc[0, "follow_ups_molecular_tests_record2"]) == round(80 / 120, 6)

    write_missing = build_missing_tables(records, WRITE_KIND)
    record_missing = build_missing_tables(records, RECORD_KIND)
    treat_write = write_missing["diagnoses_treatments"]
    treat_record = record_missing["diagnoses_treatments"]
    assert list(treat_write["ratio"])[:3] == ["2/2", "1/1", "0/1"]
    assert list(treat_record["ratio"])[:3] == ["2/2", "1/1", "0/1"]
    follow_record = record_missing["follow_ups"]
    assert "1/2" in set(follow_record["ratio"]) or follow_record.loc[1, "ratio"] == "0/1"
    assert follow_record.loc[0, "ratio"] == "2/2"
    assert follow_record.loc[1, "ratio"] == "0/1"

    out_root = Path("/tmp") / "time_stats_self_test"
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    legacy = out_root / "time"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "stale.csv").write_text("stale")
    write_dir = out_root / "time_write"
    record_dir = out_root / "time_record"
    write_dir.mkdir(parents=True, exist_ok=True)
    for name in STALE_OUTPUTS:
        (write_dir / name).write_text("stale")
    _write_kind_outputs(records, write_dir, "synthetic", WRITE_KIND)
    _write_kind_outputs(records, record_dir, "synthetic", RECORD_KIND)
    _remove_legacy_time_dir(out_root)
    for name in STALE_OUTPUTS:
        assert not (write_dir / name).exists()
    assert not legacy.exists()
    assert (write_dir / "patient_time_stats.png").exists()
    assert (write_dir / "normalized_update_time.png").exists()
    assert (write_dir / "normalized_update_time_boxplot.png").exists()
    assert (record_dir / "patient_time_stats.png").exists()
    assert (record_dir / "normalized_update_time.png").exists()
    assert (write_dir / "sequences" / "diagnoses.csv").exists()
    assert (record_dir / "sequences" / "diagnoses.csv").exists()
    assert (write_dir / "missing" / "diagnoses_treatments.csv").exists()
    assert (record_dir / "missing" / "follow_ups.csv").exists()
    diagnoses = pd.read_csv(write_dir / "sequences" / "diagnoses.csv")
    assert list(diagnoses.columns) == [
        "dataset",
        "submitter_id",
        "case_id",
        "diagnoses_updated1",
    ]
    treatments = pd.read_csv(record_dir / "sequences" / "diagnoses_treatments.csv")
    assert "diagnoses_treatments_record2" in treatments.columns
    print(
        f"self-test passed: {len(write_df)} rows, "
        f"{len(_slot_columns(write_df, WRITE_KIND))} write columns, "
        f"{len(_slot_columns(record_df, RECORD_KIND))} record columns"
    )

def run(args):
    if args.self_test:
        run_self_test()
        return

    datasets = load_dataset_configs(args.datasets_config)
    dataset_arg = args.dataset
    dataset_names = [] if dataset_arg is None else resolve_dataset_names(dataset_arg, datasets)

    output_root = Path(args.out_root) if args.out_root else OUTPUT_ROOT
    frames = []

    if not dataset_names:
        name = "custom"
        df = analyze_dataset_times(
            json_paths=args.json_path,
            dataset_name=name,
            output_dir=output_root / name,
            project_ids=[],
        )
        frames.append((name, df))
    else:
        for name in dataset_names:
            df = analyze_dataset_times(
                json_paths=get_dataset_clinic_files(name, datasets),
                dataset_name=name,
                output_dir=output_root / name,
                project_ids=get_dataset_project_ids(name, datasets),
            )
            frames.append((name, df))

    shared_dir = output_root / "_shared"
    shared_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_stale_outputs(shared_dir)
    combined = plot_patient_time_stats_all(frames, shared_dir)
    if combined is not None:
        print(f"patient_time_stats_all: {combined}")


def main():
    parser = argparse.ArgumentParser(
        description="统计每个患者的生存/随访时间，以及 t_write / t_record 实体时间",
    )
    parser.add_argument(
        "--dataset",
        default="all",
        help="数据集名；支持 all 或逗号分隔列表。传空字符串则走 --json_path 单 JSON 模式。",
    )
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument("--json_path", default=DEFAULT_JSON_PATH)
    parser.add_argument(
        "--out_root",
        default=str(OUTPUT_ROOT),
        help="输出根目录，每个数据集写到 {out_root}/{dataset}/time_write 和 time_record",
    )
    parser.add_argument(
        "--self_test",
        action="store_true",
        help="用合成病例跑一遍抽取和出图，不读真实 JSON",
    )
    args = parser.parse_args()
    if args.dataset == "":
        args.dataset = None
    run(args)


if __name__ == "__main__":
    main()
