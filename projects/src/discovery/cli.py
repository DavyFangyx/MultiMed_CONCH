"""CLI entry points for field discovery, stats, filtering, and Field Bank."""

import argparse

from common.paths import (
    DEFAULT_CKPT,
    DEFAULT_DATASETS_CONFIG,
    DEFAULT_FIELD_FILTER_RULES,
    DEFAULT_GDC_CASES_MAPPING,
    DEFAULT_JSON_FIELD_DICT,
    DEFAULT_JSON_PATH,
    VALID_ENCODINGS,
    VALID_SCHEMES,
    shared_field_stats_path,
    resolve_reference_dict_path,
    validate_encoding,
)

from .field_bank import run_field_bank
from .filter import run_field_filter
from .schemes import run_schemes
from .landmark import add_landmark_cli_args
from .longitudinal import run_longitudinal_field_bank
from .presence import run_field_presence
from .scan import run_scan
from .stats import run_field_stats


def scan_main(argv=None):
    parser = argparse.ArgumentParser(description="扫描 clinical JSON，生成每数据集字段字典")
    parser.add_argument("--dataset", default="all")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument("--json_path", default=DEFAULT_JSON_PATH)
    parser.add_argument(
        "--reference_dict",
        default=str(resolve_reference_dict_path()),
        help="扫描释义参考。默认 ClinicDatasets/gdc_clinical/field_tables/gdc_clinical_dictionary.csv",
    )
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
    parser = argparse.ArgumentParser(description="R0-R6 字段筛选，按 landmark tag 写出 fliter_log 下的 field_registry、exclusion_log，以及 kept_fields.json；--dataset all 时额外写出 rawdata_stats/_shared/{tag}/kept_fields.json 总表")
    parser.add_argument("--dataset", default="all")
    parser.add_argument("--stats_csv", default=str(shared_field_stats_path()))
    parser.add_argument(
        "--filter_rules",
        default=str(DEFAULT_FIELD_FILTER_RULES),
        help="R0/R1/R5 名单文件，默认 templates/field_filter_rules.json",
    )
    parser.add_argument(
        "--R3_coverage",
        "--min_coverage",
        type=float,
        default=0.30,
        dest="R3_coverage",
        help="R3 覆盖率下限，coverage 低于该值则删除。默认 0.30",
    )
    parser.add_argument(
        "--R4_n_unique",
        type=int,
        default=2,
        dest="R4_n_unique",
        help="R4 有效取值数下限，n_unique 低于该值则删除。默认 2",
    )
    parser.add_argument(
        "--R4_mode_share",
        "--R4_众数",
        type=float,
        default=0.95,
        dest="R4_mode_share",
        help="R4 众数占比上限，mode_share 高于该值则删除。默认 0.95",
    )
    parser.add_argument(
        "--write_templates",
        action="store_true",
        help="按 R0-R6 保留字段生成长表模板 templates/field_bank/{dataset}/{landmark_tag}/FIELD_BANK.csv（field,example,convert,unit,template）",
    )
    add_landmark_cli_args(parser, extraction=False)
    run_field_filter(parser.parse_args(argv))


def build_field_bank_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按 kept_fields.json 生成 Field Bank prompts / embeddings")
    parser.add_argument("--dataset", required=True, help="数据集名；支持 all 或逗号分隔列表")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument(
        "--kept_fields",
        default=None,
        help="覆盖默认 rawdata_stats/{dataset}/{landmark_tag}/kept_fields.json",
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
        help="只生成 outputs/{dataset}/field_bank/prompt/{landmark_tag}/prompts.csv，不调用 CONCH 编码",
    )
    parser.add_argument(
        "--rare_freq_threshold",
        type=int,
        default=5,
    )
    add_landmark_cli_args(parser, extraction=True)
    return parser


def field_bank_main(argv=None):
    parser = build_field_bank_parser()
    args = parser.parse_args(argv)
    args.encoding = validate_encoding(args.encoding)
    run_field_bank(args)


def build_schemes_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从已完成的 Field Bank prompt 基座组成 L2 / L3 / L5。--dataset 与 --landmark_time 指定基座。")
    parser.add_argument("--dataset", default="all", help="已完成的 Field Bank prompt 基座数据集，或 all")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument(
        "--scheme",
        default="all",
        choices=["all", *VALID_SCHEMES],
        help="L2、L3、L5，或 all",
    )
    parser.add_argument("--ckpt", default=DEFAULT_CKPT)
    parser.add_argument("--batch_size", type=int, default=64)
    parser.add_argument(
        "--prompts_only",
        action="store_true",
        help="只生成 outputs/{dataset}/schemes/{landmark_tag}_{L2|L3|L5}/prompts.csv，不调用 CONCH 编码",
    )
    add_landmark_cli_args(parser, extraction=True)
    return parser


def schemes_main(argv=None):
    parser = build_schemes_parser()
    args = parser.parse_args(argv)
    scheme = str(args.scheme or "all").strip()
    if scheme != "all":
        from common.paths import validate_scheme
        args.scheme = validate_scheme(scheme)
    run_schemes(args)


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


def build_longitudinal_field_bank_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="纵向 follow-up Field Bank：按记录编码，并加入 days_since / 状态变化派生列")
    parser.add_argument("--dataset", required=True, help="数据集名；支持 all 或逗号分隔列表")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument(
        "--kept_fields",
        default=None,
        help="覆盖默认 rawdata_stats/{dataset}/{landmark_tag}/kept_fields.json",
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
        help="只生成 outputs/{dataset}/longitudinal/field_bank/prompt/{landmark_tag}/prompts.csv，不调用 CONCH 编码",
    )
    parser.add_argument(
        "--rare_freq_threshold",
        type=int,
        default=5,
    )
    add_landmark_cli_args(parser, extraction=True)
    return parser


def longitudinal_field_bank_main(argv=None):
    parser = build_longitudinal_field_bank_parser()
    args = parser.parse_args(argv)
    args.encoding = validate_encoding(args.encoding)
    run_longitudinal_field_bank(args)
