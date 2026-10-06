"""CLI for the standalone PGC (SurvPGC) L0-L5 / D0-D5 line.

从 A_pipeline/src/cli.py 复制并按线裁剪：
- 只保留 json2prompt / encode / pipeline / baseline / hgcn_clinic 五个子命令
  （cindex 属于 gdc 线，不复制）；
- 删掉 --landmark_time / --landmark_shift 及所有 landmark 参数；
- 单数据源（lizhe clinical.cart），产物写 projects/outputs_pgc/。
"""

from __future__ import annotations

import argparse

from pathlib import Path

from common.clinical_io import load_clinical_cases
from .datasets import expand_source_jobs, load_source_dataset_configs
from .paths import (
    DEFAULT_BASELINE_OUT_ROOT,
    DEFAULT_CKPT,
    DEFAULT_DATASETS_CONFIG,
    DEFAULT_JSON_PATH,
    DEFAULT_OUT_DIR,
    DEFAULT_PROMPT_DIR,
    DEFAULT_TEMPLATE_DIR,
    dataset_hgcn_clinic_dir,
)

from .baseline import (
    build_baseline_feature_schema,
    build_patient_rows,
    fit_onehot_mappings,
    global_mapping_dir,
    load_baseline_scheme_fields,
    resolve_baseline_schemes,
    run_baseline_encode,
    save_global_baseline_metadata,
)
from .config import load_custom_schemes, resolve_scheme_names, SCHEME_FIELDS
from .encode import run_encode
from .json2prompt import run_json2prompt
from .hgcn_clinic import (
    load_hgcn_scheme_fields,
    prepare_hgcn_nominal_mappings,
    resolve_hgcn_schemes,
    run_hgcn_clinic,
)


def _add_common_args(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--scheme",
        default="all",
        help="方案组或单方案。manual/all = L0-L5；也可直接点名 L0 / L5。",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="数据集：all 或逗号分隔列表。读 A_pipeline_pgc/datasets.json 的 lizhe 9 个癌种。为空时使用 --json_path 单 JSON 模式。",
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
    parser.add_argument(
        "--encoding",
        default="all",
        choices=["all", "text", "baseline"],
        help="编码：text=CONCH embedding，baseline=D 向量，all=两种都处理。",
    )
    parser.add_argument(
        "--hgcn_out_root",
        default=None,
        help=(
            "hgcn_clinic 输出根目录覆盖：默认 outputs_pgc，即 outputs_pgc/{dataset}/A_manual/HGCN_clinic；"
            "给定时改写 {root}/{dataset}/A_manual/HGCN_clinic（等价性回归 / 试跑用，不碰产物根）。"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "冻结线重生成确认。本线方案冻结（L0-L5/D0-D5 被 SurvPGC_Workspace 软链消费），"
            "默认拒绝任何编码运行；显式 --force 才执行。契约见 "
            "z_notes/time_axis/frozen_schemes_contract.md。"
        ),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="A_pipeline_pgc: clinical JSON → Prompt CSV → CONCH embedding / D0-D5 baseline / HGCN clinic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "独立 PGC(SurvPGC)线：只服务 SurvPGC 论文训练，方案冻结为 L0-L5（D0-D5 = 同字段的 baseline 对照）。\n"
            "数据源固定为 datasets.json 里的 lizhe clinical.cart（无 gdc 分支、无 landmark 协议）。\n"
            "产物写到 projects/outputs_pgc/{dataset}/A_manual；由 SurvPGC_Workspace/build_workspace.sh 软链消费。\n"
            "重生成产物需用户显式决定（本线冻结）。"
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in [
        ("json2prompt", "JSON → prompt CSV"),
        ("encode", "prompt CSV → CONCH embedding"),
        ("pipeline", "json2prompt + encode"),
        ("baseline", "JSON → D0-D5 baseline vectors"),
        ("hgcn_clinic", "JSON → HGCN clinic graph-node pkl"),
    ]:
        p = sub.add_parser(name, help=help_text)
        _add_common_args(p)

    args = parser.parse_args(argv)

    if not args.force:
        print(
            "[冻结] PGC 线方案冻结(L0-L5/D0-D5,被 SurvPGC_Workspace 软链消费),"
            "默认拒绝编码运行。确认重生成请加 --force;契约与 SOP 见 "
            "z_notes/time_axis/frozen_schemes_contract.md。"
        )
        return

    load_custom_schemes(args.template_dir)
    try:
        load_baseline_scheme_fields(SCHEME_FIELDS)
        load_hgcn_scheme_fields(SCHEME_FIELDS)
    except ValueError as exc:
        parser.error(str(exc))

    if args.cmd == "baseline":
        try:
            schemes = resolve_baseline_schemes(args.scheme)
        except ValueError as exc:
            parser.error(str(exc))
    elif args.cmd == "hgcn_clinic":
        try:
            schemes = resolve_hgcn_schemes(args.scheme)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        try:
            schemes = resolve_scheme_names(args.scheme)
        except ValueError as exc:
            parser.error(str(exc))

    source_datasets = load_source_dataset_configs(args.datasets_config)
    try:
        jobs = expand_source_jobs(
            args.dataset,
            schemes,
            source_datasets,
            json_path=args.json_path,
            prompt_dir=args.prompt_dir,
            out_dir=args.out,
            baseline_out=args.baseline_out,
        )
    except ValueError as exc:
        parser.error(str(exc))

    baseline_shared = {}
    if args.cmd == "baseline" and not args.baseline_stats_dir:
        named_jobs = [job for job in jobs if job.get("name")]
        if len(named_jobs) > 1:
            dataset_names = [job["name"] for job in named_jobs]
            print(f"\n{'='*55}")
            print("[baseline] 构建多数据集共享混合编码 metadata")
            print(f"  统计范围 : {dataset_names}")
            print(f"  频次阈值 : >= {args.baseline_nominal_min_count}")
            print(f"{'='*55}")

            merged_rows = []
            for job in named_jobs:
                print(f"  -> 收集 {job['name']} 患者用于共享 nominal 词表")
                cases = load_clinical_cases(job["json_paths"], project_ids=job["project_ids"])
                merged_rows.extend(build_patient_rows(cases))

            mappings = fit_onehot_mappings(
                merged_rows,
                min_count=args.baseline_nominal_min_count,
                collapse_rare=True,
            )
            scope = {
                "type": "global_selected_datasets",
                "datasets": dataset_names,
                "patient_count": len(merged_rows),
            }
            source_mapping_dir = global_mapping_dir()
            save_global_baseline_metadata(
                metadata_dir=source_mapping_dir,
                nominal_mappings=mappings,
                feature_schema=build_baseline_feature_schema(mappings),
                nominal_min_count=args.baseline_nominal_min_count,
                dataset_names=dataset_names,
                patient_count=len(merged_rows),
            )
            print(f"  共享 mapping 已保存: {source_mapping_dir / 'category_mapping.json'}")
            baseline_shared = {
                "mappings": mappings,
                "scope": scope,
                "mapping_dir": source_mapping_dir,
            }

    if args.cmd == "hgcn_clinic":
        shared_nominal_mappings, shared_mapping_scope = prepare_hgcn_nominal_mappings(
            jobs,
            min_count=args.baseline_nominal_min_count,
        )

    for job in jobs:
        if job["name"]:
            print(f"\n######## Dataset: {job['name']} ########")
        job_schemes = list(job.get("schemes") or [])
        skipped = [scheme for scheme in schemes if scheme not in job_schemes]
        if skipped:
            print(f"  skip unbound schemes: {skipped}")
        if not job_schemes:
            print("  当前 dataset 没有可跑的绑定方案，跳过。")
            continue

        if args.cmd in ("json2prompt", "pipeline") and args.encoding in ("all", "text"):
            for scheme in job_schemes:
                run_json2prompt(
                    json_path=job["json_paths"],
                    scheme=scheme,
                    template_dir=args.template_dir,
                    prompt_dir=job["prompt_dir"],
                    project_ids=job["project_ids"],
                    dataset_name=job["name"],
                )

        if args.cmd in ("encode", "pipeline") and args.encoding in ("all", "text"):
            for scheme in job_schemes:
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
                schemes=job_schemes,
                out_root=job["baseline_out_dir"],
                project_ids=job["project_ids"],
                stats_dir=args.baseline_stats_dir,
                nominal_min_count=args.baseline_nominal_min_count,
                shared_nominal_mappings=baseline_shared.get("mappings"),
                mapping_scope=baseline_shared.get("scope"),
                global_metadata_dir=(
                    str(baseline_shared["mapping_dir"])
                    if baseline_shared.get("mapping_dir") is not None
                    else None
                ),
                dataset_name=job["name"],
            )

        if args.cmd == "hgcn_clinic":
            if job["name"]:
                hgcn_out_root = dataset_hgcn_clinic_dir(
                    job["name"],
                    base_root=args.hgcn_out_root or args.baseline_out,
                )
            elif args.hgcn_out_root:
                hgcn_out_root = str(Path(args.hgcn_out_root) / "HGCN_clinic")
            else:
                hgcn_out_root = str(Path(job["out_dir"]) / "HGCN_clinic")
            run_hgcn_clinic(
                json_paths=job["json_paths"],
                schemes=job_schemes,
                out_root=hgcn_out_root,
                project_ids=job["project_ids"],
                nominal_min_count=args.baseline_nominal_min_count,
                shared_nominal_mappings=shared_nominal_mappings,
                mapping_scope=shared_mapping_scope,
                dataset_name=job["name"],
            )


if __name__ == "__main__":
    main()
