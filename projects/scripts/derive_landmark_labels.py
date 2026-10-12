"""派生 landmark 臂 label(风险集 + 时间平移),写 results/Test_2b/arm_B/labels/。

Test_1a t0 臂(univariate)训练要求 S4 派生 label 已存在(greedy/univariate_cli.py
强制与臂 B 同患者集);cindex 路径评估时自动派生,univariate 不自动 → 本脚本是
Test_1a t0 前置步骤(landmark_0 下派生 label 与生存结局表同患者集)。

默认对数据集分档协议主集(自动派生)× landmark_0;--dataset / --landmark_time 可覆盖。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for path in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from common.paths import RESULTS_ROOT
from common.patient_set import display_to_study, main_datasets_by_label_events
from manual_pipeline.landmark_labels import build_landmark_label_file, format_risk_set_summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="派生 landmark 臂 label(写 results/Test_2b/arm_B/labels/)")
    parser.add_argument("--dataset", default=None, help="逗号分隔或单个;默认 = 分档协议主集(自动派生)")
    parser.add_argument("--landmark_time", type=int, default=0)
    args = parser.parse_args(argv)

    if args.dataset:
        datasets = [name.strip() for name in args.dataset.split(",") if name.strip()]
    else:
        datasets = main_datasets_by_label_events(100)
    for dataset in datasets:
        study = display_to_study(dataset)
        path, stats = build_landmark_label_file(
            study=study, landmark_time=args.landmark_time, results_root=RESULTS_ROOT
        )
        print(f"{dataset}: {format_risk_set_summary(stats)} -> {path}")


if __name__ == "__main__":
    main()
