"""Label-side landmark surgery (risk set + time-origin shift) for the H1b arms.

Classical landmarking (Anderson 1983; van Houwelingen dynamic prediction) is
three requirements at once (z_notes/H_series_spec.md §2.5):

1. **covariate mask** - only `t_hi <= T` values are used → `landmark.py`;
2. **risk set** - only patients still at risk at T stay in train/val/test
   (drop `ground_truth_time <= T`: died before T, or censored before T with no
   follow-up after T) → this module;
3. **time origin shift** - the endpoint time becomes `gt - T`. The c-index is
   invariant to that shift, but the spec requires it to actually happen, so it
   is implemented here and verified once by the `--landmark_shift off/on`
   invariance check.

Both label-side parts are applied by writing a derived copy of the study's
label CSV used by Clinic_Analyzer (`datasets_csv/metadata/{study}.csv`) and
pointing the conf at it through `LABEL_FILE_PATH`. The 5-fold split files are
never touched: `SurvivalDatasetFactory` intersects every split list with the
label file (`datasets/dataset_survival.py::_get_split_from_df`), so a patient
removed from the label file disappears from every fold's train/val/test.

Time units: Clinic_Analyzer's label column is in months (`LABEL_COL=
survival_months`), the landmark is in days, so the comparison uses
`gt_days = months * DAYS_PER_MONTH`. The factor only matters for the
boundary of the risk set; the shift itself is a constant that cannot change
the c-index (that is exactly what the invariance check proves).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .paths import PROJECT_ROOT


DAYS_PER_MONTH = 365.25 / 12.0
DEFAULT_TIME_COL = "survival_months"
DEFAULT_CENSORSHIP_COL = "censorship"
DEFAULT_ANALYZER_DIR = PROJECT_ROOT / "Clinic_Analyzer"
SURVPGC_ROOT = Path("/data/fangyuxuan/projects/medical_dl/SurvPGC_github_init")
LABEL_OUT_SUBDIR = Path("A_manual_landmark") / "labels"


def resolve_label_file(
    study: str,
    *,
    analyzer_dir: Path | str | None = None,
    label_file: Path | str | None = None,
) -> Path:
    """Same preference order as Clinic_Analyzer/run.sh (analyzer data, then SurvPGC)."""
    if label_file:
        return Path(label_file)
    analyzer_root = Path(analyzer_dir) if analyzer_dir else DEFAULT_ANALYZER_DIR
    candidates = (
        analyzer_root / "data" / "datasets_csv" / "metadata" / f"{study}.csv",
        SURVPGC_ROOT / "datasets_csv" / "metadata" / f"{study}.csv",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"找不到 {study} 的 label 文件，尝试过: {[str(p) for p in candidates]}"
    )


def landmark_label_path(
    *,
    study: str,
    landmark_time,
    results_root: Path | str | None = None,
    apply_shift: bool = True,
) -> Path:
    root = Path(results_root) if results_root else (PROJECT_ROOT / "results")
    suffix = "" if apply_shift else "__noshift"
    return root / LABEL_OUT_SUBDIR / f"{study}__landmark_{int(landmark_time)}{suffix}.csv"


def build_landmark_label_file(
    *,
    study: str,
    landmark_time,
    analyzer_dir: Path | str | None = None,
    label_file: Path | str | None = None,
    results_root: Path | str | None = None,
    out_path: Path | str | None = None,
    time_col: str = DEFAULT_TIME_COL,
    censorship_col: str = DEFAULT_CENSORSHIP_COL,
    apply_shift: bool = True,
) -> tuple[Path, dict]:
    """Write the landmark arm's label CSV: risk set at T + time origin at T.

    Returns (path, stats). `stats["excluded_cases"]` lists the patients removed
    by the risk-set rule, so the audit log can report the actual counts.
    """
    landmark_time = float(landmark_time)
    source = resolve_label_file(study, analyzer_dir=analyzer_dir, label_file=label_file)
    df = pd.read_csv(source, low_memory=False)
    if time_col not in df.columns:
        raise ValueError(f"label 文件缺少时间列 {time_col!r}: {source}")
    if "case_id" not in df.columns:
        raise ValueError(f"label 文件缺少 case_id 列: {source}")

    times = pd.to_numeric(df[time_col], errors="coerce")
    gt_days = times * DAYS_PER_MONTH
    # NaN (unknown ground truth time) is kept: the risk set rule only excludes
    # patients known to have left the risk set, it does not invent exclusion.
    excluded_mask = gt_days <= landmark_time
    keep_mask = ~excluded_mask

    kept = df.loc[keep_mask].copy()
    shift_months = landmark_time / DAYS_PER_MONTH
    if apply_shift:
        kept[time_col] = pd.to_numeric(kept[time_col], errors="coerce") - shift_months

    out_file = (
        Path(out_path)
        if out_path
        else landmark_label_path(
            study=study,
            landmark_time=landmark_time,
            results_root=results_root,
            apply_shift=apply_shift,
        )
    )
    out_file.parent.mkdir(parents=True, exist_ok=True)
    kept.to_csv(out_file, index=False)

    excluded_cases = sorted({str(value) for value in df.loc[excluded_mask, "case_id"]})
    kept_cases = sorted({str(value) for value in kept["case_id"]})
    stats = {
        "study": study,
        "landmark_time_days": int(landmark_time),
        "label_source": str(source),
        "label_out": str(out_file),
        "time_col": time_col,
        "censorship_col": censorship_col,
        "days_per_month": DAYS_PER_MONTH,
        "apply_shift": bool(apply_shift),
        "shift_months": shift_months if apply_shift else 0.0,
        "rows_before": int(len(df)),
        "rows_after": int(len(kept)),
        "event_rows_before": _event_rows(df, censorship_col),
        "event_rows_after": _event_rows(kept, censorship_col),
        "cases_before": int(df["case_id"].nunique()),
        "cases_after": int(kept["case_id"].nunique()),
        "excluded_rows": int(excluded_mask.sum()),
        "excluded_case_count": len(excluded_cases),
        "excluded_cases": excluded_cases,
    }
    out_file.with_suffix(".json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return out_file, stats


def _event_rows(df: pd.DataFrame, censorship_col: str) -> int | None:
    """Event rows (censorship == 0 in Clinic_Analyzer's convention), if present."""
    if censorship_col not in df.columns:
        return None
    values = pd.to_numeric(df[censorship_col], errors="coerce")
    return int((values == 0).sum())


def format_risk_set_summary(stats: dict) -> str:
    return (
        f"risk set: {stats['cases_before']} -> {stats['cases_after']} patients "
        f"(-{stats['excluded_case_count']}, gt <= {stats['landmark_time_days']}d), "
        f"rows {stats['rows_before']} -> {stats['rows_after']}, "
        f"events {stats['event_rows_before']} -> {stats['event_rows_after']}, "
        f"shift={'-' if not stats['apply_shift'] else ''}{stats['shift_months']:.4f} months"
    )


def excluded_case_ids(stats: dict) -> list[str]:
    return list(stats.get("excluded_cases") or [])
