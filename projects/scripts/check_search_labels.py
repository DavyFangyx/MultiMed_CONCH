"""投队列前闸门:检查搜索链路实际使用的 label 文件是否已剔除 gt≤0 患者。

搜索链路默认 label = Clinic_Analyzer/data/datasets_csv/metadata/{study}.csv
(greedy.data::load_survival_table);gt≤0 修复口径要求这些文件不含已知
gt≤0 患者(风险集 gt>landmark_time)。本脚本在月空间比较(survival_months ≤ 0),
不做月↔天换算;30.44 是 PGC 外部标签生产除数,见 src/common/constants.py。
本脚本只读报告,不改任何文件。
"""

from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from common.datasets import load_dataset_configs, resolve_dataset_names
from common.paths import DEFAULT_DATASETS_CONFIG
from greedy.data import DEFAULT_ANALYZER_LABEL_ROOT, display_to_study


def study_summary(dataset: str, label_root: Path = DEFAULT_ANALYZER_LABEL_ROOT) -> OrderedDict | None:
    path = label_root / f"{display_to_study(dataset)}.csv"
    if not path.exists():
        return None
    frame = pd.read_csv(path)
    months = pd.to_numeric(frame.get("survival_months", pd.Series(dtype=float)), errors="coerce")
    censorship = pd.to_numeric(frame.get("censorship", pd.Series(dtype=float)), errors="coerce")
    event = (censorship == 0).astype("Int64")  # SurvPGC:censorship=1 删失,0 事件
    le0 = months.notna() & (months <= 0)
    lt0 = months.notna() & (months < 0)
    eq0 = months.notna() & (months == 0)
    return OrderedDict(
        dataset=dataset,
        label_file=str(path),
        n_patients=len(frame),
        n_gt_le_0=int(le0.sum()),
        n_gt_lt_0=int(lt0.sum()),
        n_event_0=int((event.eq(1) & eq0).sum()),
        n_censored_0=int((event.eq(0) & eq0).sum()),
        n_no_time=int(months.isna().sum()),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="检查搜索 label 文件是否已剔除 gt≤0 患者(投 Test_6 队列前的闸门)")
    parser.add_argument("--dataset", default="all", help="数据集名;支持 all 或逗号分隔列表")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument("--label_root", default=str(DEFAULT_ANALYZER_LABEL_ROOT))
    args = parser.parse_args(argv)

    datasets = load_dataset_configs(args.datasets_config)
    selected = resolve_dataset_names(args.dataset, datasets)
    rows = [summary for name in selected if (summary := study_summary(name, Path(args.label_root)))]
    missing = [name for name in selected if study_summary(name, Path(args.label_root)) is None]
    if not rows:
        print("没有任何 label 文件可检查。")
        return

    frame = pd.DataFrame(rows)
    print(frame.to_string(index=False))
    if missing:
        print(f"\n[缺文件] {len(missing)} 个:{missing}")
    leaked = int(frame["n_gt_le_0"].sum())
    print(f"\n总 gt≤0 患者数:{leaked}")
    if leaked > 0:
        print("[闸门 FAIL] label 文件仍含 gt≤0 患者;先修复 label(landmark_labels 排除口径)再投 Test_6 队列。")
        sys.exit(1)
    else:
        print("[闸门 PASS] 所有 label 文件无已知 gt≤0 患者,可投队列。")


if __name__ == "__main__":
    main()
