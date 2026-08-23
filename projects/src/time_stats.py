"""Extract per-patient survival time and record update timestamps from clinical JSON.

Dead   -> last time = demographic.days_to_death
Not dead -> last time = diagnoses[].days_to_last_follow_up
Also keep lost_to_followup and every updated_datetime (created_datetime is ignored).
Multiple submissions of the same array stay as separate columns: {array}_updated{i}.

Field updated_datetime values are converted to days from the patient's first update,
then divided by last_time_days (days_to_death if Dead, else days_to_last_follow_up).
Values may exceed 1 when a field is updated after that last time.

Outputs in projects/rawdata_stats/{dataset}/time/:
  patient_time_stats.csv / patient_time_stats.png
  normalized_update_time.csv / normalized_update_time.png / normalized_update_time_boxplot.png

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

UPDATE_COL_RE = re.compile(r"^(.*)_updated(?:\d+)?$")
FIELD_DISPLAY_ORDER = [
    "case",
    "demographic",
    "diagnoses",
    "diagnoses_pathology_details",
    "diagnoses_treatments",
    "follow_ups",
    "follow_ups_molecular_tests",
    "follow_ups_other_clinical_attributes",
    "family_histories",
    "exposures",
]


def _is_list_of_dicts(value) -> bool:
    return isinstance(value, list) and any(isinstance(item, dict) for item in value)


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


def _collect_updated_datetimes(case: dict) -> OrderedDict:
    buckets: OrderedDict[str, dict] = OrderedDict()

    def ensure(key: str, is_array: bool) -> dict:
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {"is_array": is_array, "values": []}
            buckets[key] = bucket
        else:
            bucket["is_array"] = bucket["is_array"] or is_array
        return bucket

    def walk(obj, prefix: str, is_array_item: bool) -> None:
        if not isinstance(obj, dict):
            return

        raw = obj.get("updated_datetime")
        if _is_non_empty(raw):
            key = "updated_datetime" if prefix == "" else prefix
            bucket = ensure(key, is_array=is_array_item and prefix != "")
            bucket["values"].append(str(raw).strip())

        for child_key, child in obj.items():
            child_prefix = f"{prefix}_{child_key}" if prefix else str(child_key)
            if isinstance(child, dict):
                walk(child, child_prefix, False)
            elif _is_list_of_dicts(child):
                for item in child:
                    if isinstance(item, dict):
                        walk(item, child_prefix, True)

    walk(case, "", False)
    return buckets


def _updated_column_name(key: str, index: int, is_array: bool, n_values: int) -> str:
    if key == "updated_datetime":
        return "updated_datetime" if n_values <= 1 else f"updated_datetime{index}"
    if is_array or n_values > 1:
        return f"{key}_updated{index}"
    return f"{key}_updated"


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
    record["_updated_buckets"] = _collect_updated_datetimes(case)
    return record


def _expand_updated_columns(records: list[dict]) -> list[dict]:
    max_lens: OrderedDict[str, int] = OrderedDict()
    flags: dict[str, bool] = {}

    for record in records:
        buckets = record.get("_updated_buckets") or {}
        for key, bucket in buckets.items():
            flags[key] = flags.get(key, False) or bool(bucket.get("is_array"))
            max_lens[key] = max(max_lens.get(key, 0), len(bucket.get("values") or []))

    ordered_keys = list(max_lens.keys())
    if "updated_datetime" in ordered_keys:
        ordered_keys.remove("updated_datetime")
        ordered_keys.insert(0, "updated_datetime")

    rows = []
    for record in records:
        row = OrderedDict((k, v) for k, v in record.items() if k != "_updated_buckets")
        buckets = record.get("_updated_buckets") or {}
        for key in ordered_keys:
            n_values = max_lens[key]
            values = (buckets.get(key) or {}).get("values") or []
            is_array = flags.get(key, False)
            for i in range(1, n_values + 1):
                col = _updated_column_name(key, i, is_array, n_values)
                row[col] = values[i - 1] if i - 1 < len(values) else ""
        rows.append(row)
    return rows


def build_patient_time_frame(cases: list, dataset_name: str | None = None) -> pd.DataFrame:
    records = [extract_patient_time_record(case, dataset_name=dataset_name) for case in cases]
    rows = _expand_updated_columns(records)
    return pd.DataFrame(rows)


def _is_update_column(col: str) -> bool:
    if col == "updated_datetime" or col.startswith("updated_datetime"):
        return True
    return bool(UPDATE_COL_RE.match(col))


def _field_family(col: str) -> str:
    if col == "updated_datetime" or col.startswith("updated_datetime"):
        return "case"
    match = UPDATE_COL_RE.match(col)
    if match:
        return match.group(1)
    return col


def _ordered_fields(fields: list[str]) -> list[str]:
    known = [name for name in FIELD_DISPLAY_ORDER if name in fields]
    extra = sorted(name for name in fields if name not in known)
    return known + extra


def _days_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 86400.0


def _norm_by_last_days(dt: datetime, t_start: datetime, last_days: float) -> float | None:
    if last_days is None:
        return None
    if last_days == 0:
        return None
    return _days_between(t_start, dt) / last_days


def _update_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if _is_update_column(c)]


def build_normalized_update_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Keep every submission slot. 1 = last_time_days; values may exceed 1."""
    if df.empty:
        return pd.DataFrame()

    update_cols = _update_columns(df)
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

        vital_status = _normalize_vital_status(src.get("vital_status"))
        if _is_dead(vital_status):
            last_days = _to_float(src.get("days_to_death"))
            last_source = "demographic.days_to_death"
        else:
            last_days = _to_float(src.get("days_to_last_follow_up"))
            last_source = str(src.get("ground_truth_source") or "diagnoses.days_to_last_follow_up")

        t_min = min(all_times)
        t_max = max(all_times)
        row = OrderedDict(
            [
                ("dataset", src.get("dataset", "")),
                ("submitter_id", src.get("submitter_id", "")),
                ("case_id", src.get("case_id", "")),
                ("vital_status", vital_status),
                ("last_time_days", last_days),
                ("last_time_source", last_source),
                ("first_updated_datetime", _format_datetime(t_min)),
                ("last_updated_datetime", _format_datetime(t_max)),
                ("n_submissions", len(parsed)),
            ]
        )
        for col in update_cols:
            dt = parsed.get(col)
            if dt is None:
                row[col] = ""
                continue
            norm = _norm_by_last_days(dt, t_min, last_days)
            row[col] = "" if norm is None else round(float(norm), 6)
        rows.append(row)
    return pd.DataFrame(rows)


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


def _ordered_update_columns(df: pd.DataFrame) -> list[str]:
    cols = _update_columns(df)
    families = _ordered_fields(list(dict.fromkeys(_field_family(c) for c in cols)))
    grouped = {family: [] for family in families}
    extra = []
    for col in cols:
        family = _field_family(col)
        if family in grouped:
            grouped[family].append(col)
        else:
            extra.append(col)
    ordered = []
    for family in families:
        ordered.extend(grouped[family])
    ordered.extend(extra)
    return ordered


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

def plot_normalized_update_time(wide: pd.DataFrame, output_dir: Path, dataset_name: str) -> Path | None:
    if wide.empty:
        return None

    plt = _setup_matplotlib()
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_df = wide.copy()
    if "last_updated_datetime" in plot_df.columns:
        plot_df = plot_df.sort_values(["last_updated_datetime", "submitter_id"]).reset_index(drop=True)
    else:
        plot_df = plot_df.sort_values("submitter_id").reset_index(drop=True)
    plot_df["patient_index"] = range(1, len(plot_df) + 1)

    update_cols = _ordered_update_columns(plot_df)
    plotted_cols = []
    for col in update_cols:
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


def plot_normalized_update_time_boxplot(wide: pd.DataFrame, output_dir: Path, dataset_name: str) -> Path | None:
    if wide.empty:
        return None

    plt = _setup_matplotlib()
    output_dir.mkdir(parents=True, exist_ok=True)
    update_cols = _ordered_update_columns(wide)
    data = []
    labels = []
    for col in update_cols:
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
    ax.plot([], [], "o", color="#222222", markersize=4.5, label="离群样本")
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


def analyze_dataset_times(
    json_paths,
    dataset_name: str,
    output_dir: Path,
    project_ids: list | None = None,
) -> pd.DataFrame:
    print("######## Dataset: {} ########".format(dataset_name))
    cases = load_clinical_cases(json_paths, project_ids=project_ids)
    df = build_patient_time_frame(cases, dataset_name=dataset_name)

    output_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_stale_outputs(output_dir)

    csv_path = output_dir / "patient_time_stats.csv"
    df.to_csv(csv_path, index=False)
    png_path = plot_patient_time_stats(df, output_dir, dataset_name)
    print(f"  patient_time_stats: {csv_path}")
    print(f"  patient_time_stats: {png_path}")

    wide = build_normalized_update_frame(df)
    if not wide.empty:
        norm_csv = output_dir / "normalized_update_time.csv"
        wide.to_csv(norm_csv, index=False)
        norm_png = plot_normalized_update_time(wide, output_dir, dataset_name)
        box_png = plot_normalized_update_time_boxplot(wide, output_dir, dataset_name)
        print(f"  normalized_update_time: {norm_csv}")
        if norm_png is not None:
            print(f"  normalized_update_time: {norm_png}")
        if box_png is not None:
            print(f"  normalized_update_time: {box_png}")
    return df


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
                "days_to_last_follow_up": 120,
                "year_of_diagnosis": 2023,
                "updated_datetime": "2024-03-01T00:00:00-06:00",
                "treatments": [
                    {"updated_datetime": "2024-03-02T00:00:00-06:00"},
                    {"updated_datetime": "2024-03-03T00:00:00-06:00"},
                ],
            }
        ],
        "follow_ups": [
            {"days_to_follow_up": 80, "updated_datetime": "2024-04-01T00:00:00-06:00"},
            {"days_to_follow_up": 120, "updated_datetime": "2024-06-01T00:00:00-06:00"},
        ],
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
                "days_to_last_follow_up": 40,
                "year_of_diagnosis": 2024,
                "updated_datetime": "2024-07-01T00:00:00-06:00",
            }
        ],
        "follow_ups": [
            {"days_to_follow_up": 40, "updated_datetime": "2024-08-01T00:00:00-06:00"},
        ],
    }
    return [alive, dead]


def run_self_test() -> None:
    cases = _synthetic_cases()
    df = build_patient_time_frame(cases, dataset_name="synthetic")
    assert list(df["submitter_id"]) == ["TCGA-AA-0001", "TCGA-AA-0002"]
    assert df.loc[0, "ground_truth_time"] == 120
    assert df.loc[0, "event"] == 0
    assert df.loc[1, "ground_truth_time"] == 45
    assert df.loc[1, "event"] == 1
    assert df.loc[1, "lost_to_followup"] == "Yes"
    assert "diagnoses_updated1" in df.columns
    assert "diagnoses_treatments_updated1" in df.columns
    assert "diagnoses_treatments_updated2" in df.columns
    assert "follow_ups_updated1" in df.columns
    assert "follow_ups_updated2" in df.columns
    assert str(df.loc[0, "diagnoses_treatments_updated2"]).startswith("2024-03-03")
    follow2 = df.loc[1, "follow_ups_updated2"]
    assert follow2 == "" or pd.isna(follow2)

    wide = build_normalized_update_frame(df)
    assert not wide.empty
    assert "diagnoses_treatments_updated1" in wide.columns
    assert "diagnoses_treatments_updated2" in wide.columns
    assert "follow_ups_updated1" in wide.columns
    assert "follow_ups_updated2" in wide.columns
    assert wide.loc[0, "last_time_source"] == "diagnoses.days_to_last_follow_up"
    assert float(wide.loc[0, "last_time_days"]) == 120
    assert wide.loc[1, "last_time_source"] == "demographic.days_to_death"
    assert float(wide.loc[1, "last_time_days"]) == 45
    assert float(wide.loc[0, "follow_ups_updated1"]) < float(wide.loc[0, "follow_ups_updated2"])
    assert float(wide.loc[0, "diagnoses_treatments_updated1"]) < float(wide.loc[0, "diagnoses_treatments_updated2"])
    assert float(wide.loc[0, "follow_ups_updated2"]) > 1.0
    dead_follow2 = wide.loc[1, "follow_ups_updated2"]
    assert dead_follow2 == "" or pd.isna(dead_follow2)
    assert float(wide.loc[1, "follow_ups_updated1"]) > 1.0

    out_dir = Path("/tmp") / "time_stats_self_test"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in STALE_OUTPUTS:
        (out_dir / name).write_text("stale")
    plot_patient_time_stats(df, out_dir, "synthetic")
    plot_normalized_update_time(wide, out_dir, "synthetic")
    plot_normalized_update_time_boxplot(wide, out_dir, "synthetic")
    _cleanup_stale_outputs(out_dir)
    for name in STALE_OUTPUTS:
        assert not (out_dir / name).exists()
    assert (out_dir / "patient_time_stats.png").exists()
    assert (out_dir / "normalized_update_time.png").exists()
    assert (out_dir / "normalized_update_time_boxplot.png").exists()
    print(f"self-test passed: {len(df)} rows, {len(_update_columns(wide))} submission columns")


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
                output_dir=output_root / name / "time",
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
        description="统计每个患者的生存/随访时间，以及按最后更新时间归一化后的字段提交早晚",
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
        help="输出根目录，每个数据集写到 {out_root}/{dataset}/",
    )
    parser.add_argument(
        "--self_test",
        action="store_true",
        help="用两条合成病例跑一遍抽取和出图，不读真实 JSON",
    )
    run(parser.parse_args())


if __name__ == "__main__":
    main()
