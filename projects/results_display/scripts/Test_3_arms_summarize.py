#!/usr/bin/env python3
"""Test_3 两臂汇总:deleak/reach 写 paper_lm0/{ds}[gdc]/cindex.csv(与 Test_2b 臂 B 同表);
reach_raw 写 paper_raw/{ds}[gdc]/cindex.csv(与 Test_2b 臂 A 同表)。

职责归位(2026-10-13):整理结果成表 = results_display/scripts 的活,exp_queue 不再承担。
纯汇总,不训练;幂等(行键 = scheme×encoding×modality,重跑只补新行)。

用法(projects/ 根目录,base python):
  python3 results_display/scripts/Test_3_arms_summarize.py --arm deleak
  python3 results_display/scripts/Test_3_arms_summarize.py --arm reach --datasets TCGA-BLCA
  python3 results_display/scripts/Test_3_arms_summarize.py --arm reach_raw
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import Test_3_arms as TA  # noqa: E402
import Test_3_common as C  # noqa: E402

from manual_pipeline.cindex import summarize_dataset  # noqa: E402

ARMS = TA.ARMS


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", default="deleak", choices=ARMS)
    parser.add_argument("--datasets", default=None, help="逗号分隔数据集过滤(冒烟/调试)")
    args = parser.parse_args(argv)

    datasets = ([x.strip() for x in args.datasets.split(",") if x.strip()]
                if args.datasets else C.main_datasets())
    tag, _time = TA.arm_landmark(args.arm)
    for dataset, scheme, _work in TA.scheme_pairs(args.arm, datasets):
        jobs = TA._cindex_jobs(dataset, scheme, arm=args.arm)
        rows = summarize_dataset(
            dataset_name=f"{dataset}[gdc]", jobs=jobs,
            results_root=ROOT / "results",
            encoding="text", modality=C.ANALYZER,
            landmark_tag=tag,
        )
        print(f"[3arms][summarize] {dataset} {scheme}: {len(rows)} 行(表内累计)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
