"""Landmark-first 字段筛选:先按 t0 mask 重算字段统计,再过 R0-R6(官方链,已扶正)。

口径(Test_series_spec.md §5bis.1,2026-10-05 扶正):统计在 Field Bank 同款 landmark mask
上计算(rawdata_stats/{ds}/landmark_0/field_stats.csv),筛选用 R3_coverage=0.30 /
R4_n_unique=2 / R4_mode_share=0.95,产物写官方 rawdata_stats/{ds}/landmark_0/
{kept_fields.json, fliter_log/}。raw-first 旧口径已废弃(清理记录
z_notes/cleaned_runs_landmark_first_20261005.md)。

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

from discovery.cli import filter_main, stats_main

if __name__ == "__main__":
    stats_main(["--dataset", "all", "--landmark_time", "0"])
    # 未传 --stats_csv:filter 自动消费 _shared/landmark_0/field_stats.csv(landmark-first)
    filter_main(
        [
            "--dataset", "all",
            "--landmark_time", "0",
            "--R3_coverage", "0.30",
            "--R4_n_unique", "2",
            "--R4_mode_share", "0.95",
        ]
    )
