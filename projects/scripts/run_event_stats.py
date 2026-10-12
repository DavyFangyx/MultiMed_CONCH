import argparse
import sys
from collections import OrderedDict
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
SRC = PROJECT_ROOT / "src"

for path in (REPO_ROOT, SRC):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from common.datasets import load_dataset_configs, resolve_dataset_names
from common.paths import DEFAULT_DATASETS_CONFIG, TIME_STATS_ROOT
from time_stats import _collect_patient_time_frames

# patient_time_stats.csv 中与事件/生存终点相关的核心列
EVENT_COLUMNS = [
    "submitter_id",
    "case_id",
    "project_id",
    "vital_status",
    "lost_to_followup",
    "event",
    "ground_truth_time",
    "ground_truth_source",
    "days_to_last_follow_up",
    "days_to_death",
    "year_of_diagnosis",
]


def _read_patient_time_stats(root: Path, name: str) -> pd.DataFrame | None:
    path = root / name / "time_write" / "patient_time_stats.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


GT_LE_0_LIST_COLUMNS = [
    "submitter_id",
    "case_id",
    "category",
    "event",
    "ground_truth_time",
    "vital_status",
    "days_to_last_follow_up",
    "days_to_death",
]


def _gt_le_0_category(event, gt) -> str:
    """gt<=0 患者分类:negative(负时间)/ event_0(事件@0)/ censored_0(删失@0)/ unknown_0(状态未知@0)。"""
    if gt < 0:
        return "negative"
    if pd.isna(event):
        return "unknown_0"
    return "event_0" if event == 1 else "censored_0"


def write_dataset_event_stats(df: pd.DataFrame, output_dir: Path) -> Path:
    """写出患者级事件表 {output_dir}/event_stats.csv。

    event 列在不同数据集中可能被 pandas 写成 int(1/0)或 float(1.0/0.0),
    统一归一成 1(死亡事件)/ 0(删失)/ 空(vital_status 未知)。

    另有 {output_dir}/gt_le_0_patients.csv(仅当存在 gt<=0 患者时):
    gt<=0 占位坑患者的排除清单(见 z_notes/protocol/1_landmark/time_axis.md §2.3)。
    """
    cols = [c for c in EVENT_COLUMNS if c in df.columns]
    out = df[cols].copy()
    event = pd.to_numeric(out.get("event", pd.Series(dtype=float)), errors="coerce")
    out["event"] = event.astype("Int64")

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "event_stats.csv"
    out.to_csv(path, index=False)

    gt = pd.to_numeric(out.get("ground_truth_time", pd.Series(dtype=float)), errors="coerce")
    le0 = gt.notna() & (gt <= 0)
    if le0.any():
        sub = out[le0].copy()
        sub["category"] = [_gt_le_0_category(e, t) for e, t in zip(sub["event"], sub["ground_truth_time"])]
        keep = [c for c in GT_LE_0_LIST_COLUMNS if c in sub.columns]
        sub[keep].to_csv(output_dir / "gt_le_0_patients.csv", index=False)
    return path


def write_event_summary(dataset_frames: list[tuple[str, pd.DataFrame]], output_dir: Path) -> Path | None:
    """按数据集汇总事件数:总患者、事件、删失、未知、事件率、gt<=0 占位坑分类计数,写到 {output_dir}/event_summary.csv。"""
    if not dataset_frames:
        return None

    rows = []
    for name, df in dataset_frames:
        event = pd.to_numeric(df.get("event", pd.Series(dtype=float)), errors="coerce")
        n_event = int((event == 1).sum())
        n_censored = int((event == 0).sum())
        n_unknown = int(event.isna().sum())
        denom = n_event + n_censored

        time_num = pd.to_numeric(df.get("ground_truth_time", pd.Series(dtype=float)), errors="coerce")
        no_time = time_num.isna()
        n_event_no_time = int(((event == 1) & no_time).sum())
        n_censored_no_time = int(((event == 0) & no_time).sum())

        # gt<=0 占位坑统计(分类计数,配套 gt_le_0_patients.csv 排除清单)
        finite_le0 = time_num.notna() & (time_num <= 0)
        gt_zero = finite_le0 & (time_num == 0)
        n_gt_le_0 = int(finite_le0.sum())
        n_gt_lt_0 = int((finite_le0 & (time_num < 0)).sum())
        n_event_gt_0 = int(((event == 1) & gt_zero).sum())
        n_censored_gt_0 = int(((event == 0) & gt_zero).sum())
        n_unknown_gt_0 = int((event.isna() & gt_zero).sum())

        # label 患者集列(2026-10-09 患者级前置口径):主集门槛 = n_event_label >= 100。
        try:
            from common.patient_set import label_event_count

            label = label_event_count(name)
            label_cols = {
                "n_label_patients": label["n_patients"],
                "n_event_label": label["n_event"],
                "n_censored_label": label["n_censored"],
            }
        except FileNotFoundError:
            label_cols = {"n_label_patients": "", "n_event_label": "", "n_censored_label": ""}
        rows.append(
            OrderedDict(
                dataset=name,
                n_patients=len(df),
                n_event=n_event,
                n_censored=n_censored,
                n_unknown=n_unknown,
                event_rate=round(n_event / denom, 4) if denom else "",
                n_event_no_time=n_event_no_time,
                n_censored_no_time=n_censored_no_time,
                n_gt_le_0=n_gt_le_0,
                n_gt_lt_0=n_gt_lt_0,
                n_event_gt_0=n_event_gt_0,
                n_censored_gt_0=n_censored_gt_0,
                n_unknown_gt_0=n_unknown_gt_0,
                **label_cols,
            )
        )

    summary = pd.DataFrame(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "event_summary.csv"
    summary.to_csv(path, index=False)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="汇总各数据集的事件数(死亡事件/删失/未知),并写出患者级事件表",
    )
    parser.add_argument(
        "--dataset",
        default="all",
        help="数据集名;支持 all 或逗号分隔列表。只影响患者级 event_stats.csv 的写出范围。",
    )
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument("--out_root", default=str(TIME_STATS_ROOT), help="rawdata_stats 根目录")
    args = parser.parse_args(argv)

    root = Path(args.out_root)
    datasets = load_dataset_configs(args.datasets_config)
    selected = resolve_dataset_names(args.dataset, datasets)

    for name in selected:
        df = _read_patient_time_stats(root, name)
        if df is None:
            print(f"[跳过] {name}: 没有 time_write/patient_time_stats.csv,请先运行 scripts/run_time_stats.py")
            continue
        path = write_dataset_event_stats(df, root / name)
        print(f"{name}: {path}")

    frames = _collect_patient_time_frames(root, list(datasets.keys()))
    if not frames:
        print(f"{root} 下没有找到任何 time_write/patient_time_stats.csv,请先运行 scripts/run_time_stats.py。")
        return
    path = write_event_summary(frames, root / "_shared")
    print(f"event_summary: {path}  ({len(frames)} 个数据集)")
    print()
    print(pd.read_csv(path).to_string(index=False))


if __name__ == "__main__":
    main()
