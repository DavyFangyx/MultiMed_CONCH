"""CLI entry points for field discovery, stats, filtering, and Field Bank."""

import argparse

from common.paths import (
    DEFAULT_CKPT,
    DEFAULT_DATASETS_CONFIG,
    DEFAULT_JSON_FIELD_DICT,
    DEFAULT_JSON_PATH,
    shared_field_stats_path,
    resolve_reference_dict_path,
)

from .field_bank import run_field_bank
from .filter import run_field_filter
from .scan import run_scan
from .stats import run_field_stats


def scan_main(argv=None):
    parser = argparse.ArgumentParser(description="扫描 clinical JSON，生成每数据集字段字典")
    parser.add_argument("--dataset", default="all")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument("--json_path", default=DEFAULT_JSON_PATH)
    parser.add_argument("--reference_dict", default=str(resolve_reference_dict_path()))
    parser.add_argument("--out", default=None)
    run_scan(parser.parse_args(argv))


def stats_main(argv=None):
    parser = argparse.ArgumentParser(description="基于扫描字典统计 JSON 全字段覆盖率 / 三态缺失")
    parser.add_argument("--dataset", default="all")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument("--json_path", default=DEFAULT_JSON_PATH)
    parser.add_argument(
        "--json_field_dict",
        default=str(DEFAULT_JSON_FIELD_DICT),
        help="覆盖字段字典路径。默认优先 rawdata_stats/{dataset}/scanned_fields.json",
    )
    run_field_stats(parser.parse_args(argv))


def filter_main(argv=None):
    parser = argparse.ArgumentParser(description="R0-R6 字段筛选，按数据集写出 fliter_log 下的 field_registry、exclusion_log、active_fields")
    parser.add_argument("--dataset", default="all")
    parser.add_argument("--stats_csv", default=str(shared_field_stats_path()))
    parser.add_argument("--min_coverage", type=float, default=0.30)
    parser.add_argument(
        "--write_templates",
        action="store_true",
        help="按 R0-R6 保留字段生成长表模板 templates/B_scan/{dataset}/FIELD_BANK.csv（field,example,convert,unit,template）",
    )
    run_field_filter(parser.parse_args(argv))


def field_bank_main(argv=None):
    parser = argparse.ArgumentParser(description="按 active_fields.json 生成 Field Bank prompts / embeddings")
    parser.add_argument("--dataset", required=True, help="数据集名；支持 all 或逗号分隔列表")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument(
        "--active_fields",
        default=None,
        help="覆盖默认 rawdata_stats/{dataset}/fliter_log/active_fields.json",
    )
    parser.add_argument("--ckpt", default=DEFAULT_CKPT)
    parser.add_argument("--batch_size", type=int, default=64)
    parser.add_argument(
        "--prompts_only",
        action="store_true",
        help="只生成 outputs/{dataset}/B_scan/FIELD_BANK/prompts.csv，不调用 CONCH 编码",
    )
    run_field_bank(parser.parse_args(argv))
