"""CLI for the H1a leakage audit (spec §5)."""

from __future__ import annotations

import argparse

from common.paths import DEFAULT_DATASETS_CONFIG
from .audit import (
    DEFAULT_EVENT_SUMMARY,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_TEMPLATES_ROOT,
    LANDMARK_T0,
    LEAK_SCHEMES,
    run_audit,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "H1a 泄露审计：对 datasets.json 全部注册队列 × 10 个论文方案，"
            "逐字段量化 t0 时刻不可得的患者比例（无训练，纯描述性统计）。"
        )
    )
    parser.add_argument("--datasets_config", default=str(DEFAULT_DATASETS_CONFIG))
    parser.add_argument(
        "--dataset",
        default="all",
        help="数据集名（逗号分隔）或 all；默认 all = datasets.json 全部注册队列",
    )
    parser.add_argument(
        "--schemes",
        default=",".join(LEAK_SCHEMES),
        help="方案名（逗号分隔）；默认 10 个论文方案",
    )
    parser.add_argument("--templates_root", default=str(DEFAULT_TEMPLATES_ROOT))
    parser.add_argument(
        "--out_dir",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="产物根目录，默认 results/leak_audit",
    )
    parser.add_argument(
        "--event_summary",
        default=str(DEFAULT_EVENT_SUMMARY),
        help="队列事件汇总 CSV（用于汇总表并列 n_event/event_rate）",
    )
    parser.add_argument(
        "--landmark_time",
        type=int,
        default=LANDMARK_T0,
        help="landmark 天数，主口径 t0=0",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    schemes = [item.strip() for item in str(args.schemes).split(",") if item.strip()]
    if not schemes:
        print("❌ --schemes 为空")
        return 2
    result = run_audit(
        datasets_config=args.datasets_config,
        dataset=args.dataset,
        schemes=schemes,
        templates_root=args.templates_root,
        out_dir=args.out_dir,
        event_summary=args.event_summary,
        landmark_time=int(args.landmark_time),
        quiet=bool(args.quiet),
    )
    print(
        f"完成：{result['n_datasets']} 个数据集 × {result['n_schemes']} 个方案 "
        f"→ {result['n_payloads']} 个明细 JSON"
    )
    print(f"汇总表: {result['summary_csv']}")
    return 0
