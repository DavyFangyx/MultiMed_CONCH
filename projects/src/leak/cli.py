"""CLI for the Test_2a leakage audit (spec §2.1 / §5)."""

from __future__ import annotations

import argparse

from common.paths import DEFAULT_DATASETS_CONFIG
from .audit import (
    BINDING_ALL,
    BINDING_SPEC,
    DEFAULT_EVENT_SUMMARY,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_TEMPLATES_ROOT,
    LEAK_SCHEMES,
    run_audit,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Test_2a 泄露审计（新口径，spec §2.1）：按 §2.4 绑定（HGCN_* 仅其对应癌种、"
            "泛癌种 × 33 TCGA、剔除 CPTAC/MMRF，共 138 个组合）逐字段量化"
            "「实际进入模型的值来自 t_hi > 0 槽位」的患者比例（无训练，纯描述性统计）。"
            "取值直接走 A_pipeline 的 extract_values（无泄露处理），来源槽位时点用 "
            "src/time_stats.py 的 t_hi。"
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
        help="产物根目录，默认 results/Test_2a_leak_audit",
    )
    parser.add_argument(
        "--event_summary",
        default=str(DEFAULT_EVENT_SUMMARY),
        help="队列事件汇总 CSV（用于汇总表并列 n_event/event_rate）",
    )
    parser.add_argument(
        "--no_g1",
        action="store_true",
        help="跳过 Test_1a 消费的逐字段审计（G1_{md5(field_idx)}.json）",
    )
    parser.add_argument(
        "--binding",
        choices=(BINDING_SPEC, BINDING_ALL),
        default=BINDING_SPEC,
        help=(
            "spec = 按 spec §2.4 绑定（默认：HGCN_* 仅其癌种、泛癌种 × 33 TCGA）；"
            "all = 放宽方案绑定（仅 ad-hoc 方案用）；两种模式都剔除 CPTAC/MMRF"
        ),
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="先删除 out_dir 下不在本次计划内的 {dataset}/{scheme}.json（及空目录）",
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
        binding=args.binding,
        prune=bool(args.prune),
        g1=not bool(args.no_g1),
        quiet=bool(args.quiet),
    )
    print(
        f"完成（binding={result['binding']}）：{result['n_datasets']} 个数据集 / "
        f"{result['n_schemes']} 个方案 → {result['n_pairs']} 个绑定组合、"
        f"{result['n_payloads']} 个明细 JSON、{result['n_g1_payloads']} 个 G1 逐字段 JSON"
    )
    print(f"汇总表: {result['summary_csv']}")
    return 0
