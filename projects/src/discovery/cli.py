"""CLI entry points for field discovery, stats, filtering, and Field Bank."""

import argparse

from common.paths import (
    DEFAULT_CKPT,
    DEFAULT_DATASETS_CONFIG,
    DEFAULT_GDC_CASES_MAPPING,
    DEFAULT_JSON_FIELD_DICT,
    DEFAULT_JSON_PATH,
    VALID_ENCODINGS,
    shared_field_stats_path,
    resolve_reference_dict_path,
    validate_encoding,
)

from .field_bank import run_field_bank
from .filter import run_field_filter
from .presence import run_field_presence
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
    parser = argparse.ArgumentParser(description="R0-R6 字段筛选，按数据集写出 fliter_log 下的 field_registry、exclusion_log，以及 kept_fields.json；--dataset all 时额外写出 rawdata_stats/_shared/kept_fields.json 总表")
    parser.add_argument("--dataset", default="all")
    parser.add_argument("--stats_csv", default=str(shared_field_stats_path()))
    parser.add_argument("--min_coverage", type=float, default=0.30)
    parser.add_argument(
        "--write_templates",
        action="store_true",
        help="按 R0-R6 保留字段生成长表模板 templates/field_bank/{dataset}/FIELD_BANK.csv（field,example,convert,unit,template）",
    )
    run_field_filter(parser.parse_args(argv))


def build_field_bank_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按 kept_fields.json 生成 Field Bank prompts / embeddings")
    parser.add_argument("--dataset", required=True, help="数据集名；支持 all 或逗号分隔列表")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument(
        "--kept_fields",
        default=None,
        help="覆盖默认 rawdata_stats/{dataset}/kept_fields.json",
    )
    parser.add_argument(
        "--encoding",
        default="prompt",
        choices=list(VALID_ENCODINGS),
    )
    parser.add_argument("--ckpt", default=DEFAULT_CKPT)
    parser.add_argument("--batch_size", type=int, default=64)
    parser.add_argument(
        "--prompts_only",
        action="store_true",
        help="只生成 outputs/{dataset}/field_bank/prompt/prompts.csv，不调用 CONCH 编码",
    )
    parser.add_argument(
        "--rare_freq_threshold",
        type=int,
        default=5,
    )
    return parser


def field_bank_main(argv=None):
    parser = build_field_bank_parser()
    args = parser.parse_args(argv)
    args.encoding = validate_encoding(args.encoding)
    run_field_bank(args)


def presence_main(argv=None):
    parser = argparse.ArgumentParser(description="对照官方 mapping 统计 clinical JSON 字段是否出现")
    parser.add_argument("--dataset", default="all")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument(
        "--mapping_csv",
        default=str(DEFAULT_GDC_CASES_MAPPING),
        help="官方 clinical JSON 字段总表，默认 ClinicDatasets/gdc_clinical/field_tables/gdc_cases_mapping.csv",
    )
    run_field_presence(parser.parse_args(argv))
