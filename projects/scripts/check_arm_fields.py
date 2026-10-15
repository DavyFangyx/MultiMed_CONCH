#!/usr/bin/env python3
"""臂字段解析检查(主线外的阶段检查工具,只读,不写任何产物)。

训练时索引(2026-10-13 拍板)之后,主线没有切片文件;本脚本把"名单 ∩ bank → 位号"
物化成审计视图:每个 (dataset, arm) 一行,列出保留字段数、丢弃字段、bank 指纹。
用途:enqueue 前人工核查"每个臂在每个数据集上实际拿到的字段"。

用法(projects/ 根目录,base python):
  python3 scripts/check_arm_fields.py --arm deleak
  python3 scripts/check_arm_fields.py --arm reach --datasets TCGA-BLCA,TCGA-GBM
  python3 scripts/check_arm_fields.py --arm raw    # 2b 报告值臂(work × raw)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from manual_pipeline.arm_names import (  # noqa: E402
    bank_dir,
    bank_fingerprint,
    greedy_fields,
    greedy_result_json,
    greedy_scheme_name,
    resolve_field_indices,
    template_fields,
    template_json,
    work_scheme_name,
)

import Test_3_common as C  # noqa: E402


def arm_rows(dataset: str, arm: str) -> list[tuple[str, list[str], str, str]]:
    """[(scheme, wanted_fields, t, source_note)]。"""
    rows = []
    if arm in ("raw", "lm0"):
        t = arm
        for _, work in C.work_pairs([dataset]):
            rows.append((work_scheme_name(work, dataset, t), template_fields(template_json(work)), t, f"work={work}"))
    elif arm in ("deleak", "reach", "reach_best"):
        t = "lm0"
        if arm == "deleak":
            for _, work in C.work_pairs([dataset]):
                rows.append((work_scheme_name(work, dataset, t), template_fields(template_json(work)), t, f"work={work}"))
        else:
            kind = "best" if arm == "reach_best" else "ksig"
            result = greedy_result_json(dataset)
            if not result.exists():
                return []
            rows.append((greedy_scheme_name(dataset, kind=kind), greedy_fields(result, kind=kind), t, "greedy=result.json"))
    else:
        raise SystemExit(f"未知臂: {arm}(可选 raw / lm0 / deleak / reach / reach_best)")
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, help="raw / lm0 / deleak / reach / reach_best")
    parser.add_argument("--datasets", default=None, help="逗号分隔数据集过滤(默认全部主集)")
    args = parser.parse_args(argv)

    if args.datasets:
        datasets = [x.strip() for x in args.datasets.split(",") if x.strip()]
    else:
        datasets = C.main_datasets()

    print(f"{'dataset':12s} {'scheme':46s} {'T':3s} {'keep':>4s} {'drop':>4s}  bank_fp       source")
    fail = 0
    for dataset in datasets:
        for scheme, wanted, t, note in arm_rows(dataset, args.arm):
            try:
                idx, keep = resolve_field_indices(bank_dir(dataset, t), wanted)
            except FileNotFoundError as exc:
                print(f"{dataset:12s} {scheme:46s} {t:3s}  BANK 缺失: {exc}")
                fail += 1
                continue
            dropped = [f for f in wanted if f not in keep]
            print(f"{dataset:12s} {scheme:46s} {t:3s} {len(keep):4d} {len(dropped):4d}  "
                  f"{bank_fingerprint(bank_dir(dataset, t))}  {note}")
            if dropped:
                print(f"{'':12s} {'':46s}     drop: {dropped}")
            if not keep:
                fail += 1
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
