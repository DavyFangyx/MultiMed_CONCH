"""CLI for human-defined L0-L5 / D0-D5 / paper-scheme / HGCN_clinic workflows."""

from __future__ import annotations

import argparse

from pathlib import Path

from common.clinical_io import load_clinical_cases
from .datasets import expand_source_jobs, load_source_dataset_configs
from .paths import (
    DEFAULT_BASELINE_OUT_ROOT,
    DEFAULT_CKPT,
    DEFAULT_DATASETS_CONFIG,
    DEFAULT_GDC_DATASETS_CONFIG,
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
from .config import load_custom_schemes, resolve_scheme_names
from .encode import run_encode
from .json2prompt import run_json2prompt
from .hgcn_clinic import (
    load_hgcn_scheme_fields,
    prepare_hgcn_nominal_mappings,
    resolve_hgcn_schemes,
    run_hgcn_clinic,
)
from .cindex import resolve_cindex_schemes, run_cindex_queue
from .config import SCHEME_FIELDS


def _add_common_args(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--scheme",
        default="all",
        help="方案组或单方案。所有命令相同：manual=L0-L5，paper=论文方案，all=L0-L5+论文方案。也可指定 L0 / MULTISURV 等单个方案。",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="数据集。所有命令相同：all 或逗号分隔列表。L0-L5 / D0-D5 默认读 A_pipeline/datasets.json 的 lizhe 9 个癌种；论文方案展开官方 33 个 TCGA。为空时使用 --json_path 单 JSON 模式。",
    )
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument("--gdc_datasets_config", default=DEFAULT_GDC_DATASETS_CONFIG)
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
        help="编码。所有命令相同：text=CONCH embedding，baseline=D 向量，all=两种都处理。cindex 按它选评测编码。",
    )
    parser.add_argument(
        "--modality",
        default="mlp_clinic_flatten",
        help="cindex 评估模型，逗号分隔。没有内外层。默认 mlp_clinic_flatten；可选 mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten,clinic_cox,survgc_f,survpgc_f。",
    )
    parser.add_argument(
        "--results_dir",
        default=None,
        help="cindex 汇总表根目录，默认 projects/results。",
    )
    parser.add_argument(
        "--reuse",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="cindex 复用已有 fold CSV。",
    )
    parser.add_argument("--max_epochs", type=int, default=None, help="cindex 训练轮数。默认走 Analyzer。")
    parser.add_argument("--seed", type=int, default=0, help="cindex 随机种子。")
    parser.add_argument(
        "--queue_root",
        default=None,
        help="cindex conf 队列根目录。默认 Clinic_Analyzer/configs/A_manual/{queue,running,done,failed}",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="本终端同时抢活的 worker 数。每个 worker 独立 claim 一条 conf。多 GPU 请开多个终端并设 CUDA_VISIBLE_DEVICES。",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="A_pipeline: JSON → Prompt CSV → CONCH embedding / D0-D5+paper baseline / HGCN clinic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "L0-L5 / D0-D5 / 论文方案 / HGCN_clinic 是独立的人工方案通路，默认读 A_pipeline/datasets.json 中的 lizhe clinical.cart。\n"
            "--scheme / --dataset / --encoding 在所有命令里定义相同。scheme: manual=L0-L5，paper=论文方案，all=两组。encoding: text=CONCH embedding，baseline=D 向量，all=两种都处理。hgcn_clinic 只落地 L0-L5。\n"
            "每个方案在 templates/{scheme}/fields.json 写 source=lizhe|gdc。L0-L5 / D0-D5 用 lizhe 9 个；paper 绑定全部 33 个 TCGA + GDC raw_json。--dataset all 按方案来源展开。\n"
            "产物写到 outputs/{dataset}/A_manual；cindex 把 conf 写入 Clinic_Analyzer/configs/A_manual/{queue,running,done,failed}，再由 run.sh 抢活；汇总表写到 results/A_manual。Field Bank / greedy 请使用 projects/scripts 下的 B 通路入口。"
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in [
        ("json2prompt", "JSON → prompt CSV"),
        ("encode", "prompt CSV → CONCH embedding"),
        ("pipeline", "json2prompt + encode"),
        ("baseline", "JSON → D0-D5 / paper-scheme baseline vectors"),
        ("hgcn_clinic", "JSON → HGCN clinic graph-node pkl"),
        ("cindex", "A_manual embeddings → Clinic_Analyzer queue → 5-fold val c-index"),
    ]:
        p = sub.add_parser(name, help=help_text)
        _add_common_args(p)

    args = parser.parse_args(argv)

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
    elif args.cmd == "cindex":
        try:
            schemes = resolve_cindex_schemes(args.scheme, args.encoding)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        try:
            schemes = resolve_scheme_names(args.scheme)
        except ValueError as exc:
            parser.error(str(exc))

    source_datasets = load_source_dataset_configs(
        lizhe_config=args.datasets_config,
        gdc_config=args.gdc_datasets_config,
    )
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

    baseline_mappings_by_source = {}
    if args.cmd == "baseline" and not args.baseline_stats_dir:
        jobs_by_source = {}
        for job in jobs:
            if not job.get("name"):
                continue
            jobs_by_source.setdefault(job.get("source") or "lizhe", []).append(job)
        for source, source_jobs in jobs_by_source.items():
            if len(source_jobs) <= 1:
                continue
            dataset_names = [job["name"] for job in source_jobs]
            print(f"\n{'='*55}")
            print("[baseline] 构建多数据集共享混合编码 metadata")
            print(f"  来源     : {source}")
            print(f"  统计范围 : {dataset_names}")
            print(f"  频次阈值 : >= {args.baseline_nominal_min_count}")
            print(f"{'='*55}")

            merged_rows = []
            for job in source_jobs:
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
                "source": source,
                "datasets": dataset_names,
                "patient_count": len(merged_rows),
            }
            source_mapping_dir = global_mapping_dir(source)
            save_global_baseline_metadata(
                metadata_dir=source_mapping_dir,
                nominal_mappings=mappings,
                feature_schema=build_baseline_feature_schema(mappings),
                nominal_min_count=args.baseline_nominal_min_count,
                dataset_names=dataset_names,
                patient_count=len(merged_rows),
            )
            print(f"  共享 mapping 已保存: {source_mapping_dir / 'category_mapping.json'}")
            baseline_mappings_by_source[source] = {
                "mappings": mappings,
                "scope": scope,
                "mapping_dir": source_mapping_dir,
            }

    if args.cmd == "cindex":
        named_jobs = [job for job in jobs if job["name"]]
        if not named_jobs:
            parser.error("cindex 需要 --dataset，不能走单 JSON 模式")
        run_cindex_queue(
            jobs=named_jobs,
            baseline_out=args.baseline_out,
            encoding=args.encoding,
            modality=args.modality,
            results_root=args.results_dir,
            reuse=args.reuse,
            max_epochs=args.max_epochs,
            seed=args.seed,
            queue_root=args.queue_root,
            workers=args.workers,
        )
        return

    if args.cmd == "hgcn_clinic":
        shared_nominal_mappings, shared_mapping_scope = prepare_hgcn_nominal_mappings(
            jobs,
            min_count=args.baseline_nominal_min_count,
        )

    for job in jobs:
        if job["name"]:
            print(f"\n######## Dataset: {job['name']} [{job.get('source') or 'custom'}] ########")
        job_schemes = list(job.get("schemes") or [])
        skipped = [scheme for scheme in schemes if scheme not in job_schemes]
        if skipped:
            print(f"  skip unbound schemes: {skipped}")
        if not job_schemes:
            print("  当前 dataset 没有可跑的绑定方案，跳过。")
            continue

        if args.cmd in ("json2prompt", "pipeline"):
            for scheme in job_schemes:
                run_json2prompt(
                    json_path=job["json_paths"],
                    scheme=scheme,
                    template_dir=args.template_dir,
                    prompt_dir=job["prompt_dir"],
                    project_ids=job["project_ids"],
                    dataset_name=job["name"],
                )

        if args.cmd in ("encode", "pipeline"):
            for scheme in job_schemes:
                run_encode(
                    scheme=scheme,
                    prompt_dir=job["prompt_dir"],
                    ckpt=args.ckpt,
                    out_dir=job["out_dir"],
                    batch_size=args.batch_size,
                )

        if args.cmd == "baseline":
            source = job.get("source") or "lizhe"
            source_meta = baseline_mappings_by_source.get(source) or {}
            run_baseline_encode(
                json_paths=job["json_paths"],
                schemes=job_schemes,
                out_root=job["baseline_out_dir"],
                project_ids=job["project_ids"],
                stats_dir=args.baseline_stats_dir,
                nominal_min_count=args.baseline_nominal_min_count,
                shared_nominal_mappings=source_meta.get("mappings"),
                mapping_scope=source_meta.get("scope"),
                global_metadata_dir=(
                    str(source_meta["mapping_dir"]) if source_meta.get("mapping_dir") is not None else None
                ),
            )

        if args.cmd == "hgcn_clinic":
            if job["name"]:
                hgcn_out_root = dataset_hgcn_clinic_dir(
                    job["name"],
                    base_root=args.baseline_out,
                )
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
