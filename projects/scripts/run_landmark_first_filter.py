"""Landmark-first 字段筛选:先按 t0 mask 重算字段统计,再过 R0-R6。

口径(Test_series_spec.md §5bis.1):统计在 Field Bank 同款 landmark mask 上计算
(rawdata_stats/{ds}/landmark_0/field_stats.csv),筛选用 R3_coverage=0.30 /
R4_n_unique=2 / R4_mode_share=0.95,产物写 rawdata_stats/{ds}/landmark_0_t0stats/,
不覆盖官方 field_stats.csv 与官方 landmark_0/kept_fields.json。

验收:scripts/validate_t0stats_vs_masks.py 与 t0 臂 .pt mask 逐字段比对(diff <= 1e-5)。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
SRC = PROJECT_ROOT / "src"

for path in (REPO_ROOT, SRC):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from common.paths import shared_field_stats_path
from discovery.cli import filter_main, stats_main

if __name__ == "__main__":
    stats_main(["--dataset", "all", "--landmark_time", "0"])
    filter_main(
        [
            "--dataset", "all",
            "--landmark_time", "0",
            "--stats_csv", str(shared_field_stats_path("landmark_0")),
            "--R3_coverage", "0.30",
            "--R4_n_unique", "2",
            "--R4_mode_share", "0.95",
            "--out_suffix", "t0stats",
        ]
    )
