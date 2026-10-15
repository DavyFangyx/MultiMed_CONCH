#!/usr/bin/env python3
"""Test_2b 汇总:把两臂 run 折文件收成表 results/{paper_raw,paper_lm0}/{ds}[gdc]/cindex.csv。

职责归位(2026-10-13):整理结果成表 = results_display/scripts 的活,exp_queue 不再承担。
纯汇总,不训练;幂等(表已存在的行保序不重复,重跑只补新行)。

用法(projects/ 根目录,base python):
  python3 results_display/scripts/Test_2b_summarize.py                  # 两臂全量
  python3 results_display/scripts/Test_2b_summarize.py --datasets TCGA-BLCA,TCGA-GBM
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import exp_queue as EQ  # noqa: E402  复用 2b 臂模板与波次网格(s4_*)

from manual_pipeline.cindex import summarize_dataset  # noqa: E402
from manual_pipeline.landmark import parse_landmark_setting  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", default=None, help="逗号分隔数据集过滤(冒烟/调试)")
    args = parser.parse_args(argv)

    arm = EQ._ARM_2B
    combos = EQ.s4_work_combos()
    if args.datasets:
        allow = {x.strip() for x in args.datasets.split(",") if x.strip()}
        combos = [c for c in combos if c[0] in allow]
    for t in ("raw", "lm0"):
        landmark = parse_landmark_setting(EQ.T2B_ARMS[t])
        jobs = EQ.s4_jobs_for_combos(arm, combos, t)
        by_dataset: dict[str, list[dict]] = {}
        for job in jobs:
            # 表目录键沿用 "{dataset}[gdc]"(与 arm_B 表同键,行合并不分家)。
            by_dataset.setdefault(f"{job['dataset']}[gdc]", []).append(job)
        for dataset, dataset_jobs in sorted(by_dataset.items()):
            print(f"[2b][summarize] T={t} {dataset}", flush=True)
            summarize_dataset(
                dataset_name=dataset,
                jobs=dataset_jobs,
                results_root=arm.extras["cindex_results_root"],
                encoding=EQ.T2B_ENCODING,
                modality=",".join(EQ.T2B_ANALYZERS),
                landmark_tag=landmark.arm_tag,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
