"""CLI for human-defined L0-L5 / D0-D5 scheme workflows."""

import argparse

from common.clinical_io import load_clinical_cases
from common.datasets import dataset_jobs, load_dataset_configs, resolve_dataset_names
from common.paths import (
    DEFAULT_BASELINE_OUT_ROOT,
    DEFAULT_CKPT,
    DEFAULT_DATASETS_CONFIG,
    DEFAULT_JSON_PATH,
    DEFAULT_OUT_DIR,
    DEFAULT_PROMPT_DIR,
    DEFAULT_TEMPLATE_DIR,
)

from .baseline import (
    build_baseline_feature_schema,
    build_patient_rows,
    fit_nominal_mappings,
    global_mapping_dir,
    resolve_baseline_schemes,
    run_baseline_encode,
    save_global_baseline_metadata,
)
from .config import load_custom_schemes, resolve_scheme_names
from .encode import run_encode
from .json2prompt import run_json2prompt


def prompt_stats_main(argv=None):
    from common.paths import DEFAULT_PROMPT_DIR, DEFAULT_TEMPLATE_DIR, PROJECT_ROOT
    from .prompt_stats import run_prompt_stats

    parser = argparse.ArgumentParser(description="L0-L5 prompt CSV 占位率对照（不读原始 JSON 全字段）")
    parser.add_argument("--scheme", default="all")
    parser.add_argument("--dataset", default="all")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument("--json_path", default=DEFAULT_JSON_PATH)
    parser.add_argument("--template_dir", default=DEFAULT_TEMPLATE_DIR)
    parser.add_argument("--prompt_dir", default=DEFAULT_PROMPT_DIR)
    parser.add_argument("--out", default=DEFAULT_PROMPT_DIR)
    run_prompt_stats(parser.parse_args(argv))


def _add_common_args(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--scheme",
        default="all",
        help="方案名；文本流程支持 L0-L5 / v1 自定义方案，baseline 流程支持 D0-D5。all 表示运行当前命令支持的全部方案。",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="数据集名；支持 all 或逗号分隔列表。为空时使用 --json_path 单数据集模式。",
    )
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument("--json_path", default=DEFAULT_JSON_PATH)
    parser.add_argument("--template_dir", default=DEFAULT_TEMPLATE_DIR)
    parser.add_argument("--prompt_dir", default=DEFAULT_PROMPT_DIR)
    parser.add_argument("--ckpt", default=DEFAULT_CKPT)
    parser.add_argument("--out", default=DEFAULT_OUT_DIR)
    parser.add_argument("--batch_size", type=int, default=64)
    parser.add_argument("--baseline_out", default=DEFAULT_BASELINE_OUT_ROOT)
    parser.add_argument("--baseline_stats_dir", default=None)
    parser.add_argument("--baseline_nominal_min_count", type=int, default=5)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Scheme pipeline: JSON → Prompt CSV → CONCH embedding / D0-D5 baseline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "L0-L5 / D0-D5 是人工定义字段的方案通路。\n"
            "FIELD_BANK / 字段扫描请使用 projects/scripts/run_scan_fields.py、"
            "run_field_stats.py、run_field_filter.py、run_field_bank.py。"
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in [
        ("json2prompt", "JSON → prompt CSV"),
        ("encode", "prompt CSV → CONCH embedding"),
        ("pipeline", "json2prompt + encode"),
        ("baseline", "JSON → D0-D5 baseline vectors"),
    ]:
        p = sub.add_parser(name, help=help_text)
        _add_common_args(p)

    args = parser.parse_args(argv)

    if args.cmd == "baseline":
        try:
            schemes = resolve_baseline_schemes(args.scheme)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        load_custom_schemes(args.template_dir)
        try:
            schemes = resolve_scheme_names(args.scheme)
        except ValueError as exc:
            parser.error(str(exc))

    datasets = load_dataset_configs(args.datasets_config)
    jobs = dataset_jobs(
        args.dataset,
        datasets,
        json_path=args.json_path,
        prompt_dir=args.prompt_dir,
        out_dir=args.out,
        baseline_out=args.baseline_out,
    )

    shared_nominal_mappings = None
    shared_mapping_scope = None
    mapping_dir = None
    if args.cmd == "baseline" and len(jobs) > 1 and not args.baseline_stats_dir:
        dataset_names = resolve_dataset_names(args.dataset, datasets)
        print(f"\n{'='*55}")
        print("[baseline] 构建多数据集共享混合编码 metadata")
        print(f"  统计范围 : {dataset_names}")
        print(f"  频次阈值 : >= {args.baseline_nominal_min_count}")
        print(f"{'='*55}")

        merged_rows = []
        for job in jobs:
            print(f"  -> 收集 {job['name']} 患者用于共享 nominal 词表")
            cases = load_clinical_cases(job["json_paths"], project_ids=job["project_ids"])
            merged_rows.extend(build_patient_rows(cases))

        shared_nominal_mappings = fit_nominal_mappings(
            merged_rows,
            min_count=args.baseline_nominal_min_count,
            collapse_rare=True,
        )
        shared_mapping_scope = {
            "type": "global_selected_datasets",
            "datasets": dataset_names,
            "patient_count": len(merged_rows),
        }
        mapping_dir = global_mapping_dir()
        save_global_baseline_metadata(
            metadata_dir=mapping_dir,
            nominal_mappings=shared_nominal_mappings,
            feature_schema=build_baseline_feature_schema(shared_nominal_mappings),
            nominal_min_count=args.baseline_nominal_min_count,
            dataset_names=dataset_names,
            patient_count=len(merged_rows),
        )
        print(f"  共享 mapping 已保存: {mapping_dir / 'category_mapping.json'}")

    for job in jobs:
        if job["name"]:
            print(f"\n######## Dataset: {job['name']} ########")

        if args.cmd in ("json2prompt", "pipeline"):
            for scheme in schemes:
                run_json2prompt(
                    json_path=job["json_paths"],
                    scheme=scheme,
                    template_dir=args.template_dir,
                    prompt_dir=job["prompt_dir"],
                    project_ids=job["project_ids"],
                    dataset_name=job["name"],
                )

        if args.cmd in ("encode", "pipeline"):
            for scheme in schemes:
                run_encode(
                    scheme=scheme,
                    prompt_dir=job["prompt_dir"],
                    ckpt=args.ckpt,
                    out_dir=job["out_dir"],
                    batch_size=args.batch_size,
                )

        if args.cmd == "baseline":
            run_baseline_encode(
                json_paths=job["json_paths"],
                schemes=schemes,
                out_root=job["baseline_out_dir"],
                project_ids=job["project_ids"],
                stats_dir=args.baseline_stats_dir,
                nominal_min_count=args.baseline_nominal_min_count,
                shared_nominal_mappings=shared_nominal_mappings,
                mapping_scope=shared_mapping_scope,
                global_metadata_dir=(
                    str(mapping_dir)
                    if shared_nominal_mappings is not None and shared_mapping_scope is not None
                    else None
                ),
            )


if __name__ == "__main__":
    main()
