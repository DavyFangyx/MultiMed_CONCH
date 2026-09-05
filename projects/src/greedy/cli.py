"""CLI for the nested greedy scheduler."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from timeit import default_timer as timer

from common.datasets import load_dataset_configs, resolve_dataset_names
from common.paths import DEFAULT_DATASETS_CONFIG, VALID_ENCODINGS, dataset_field_bank_dir, dataset_greedy_dir, experiment_from_args, landmark_tag_from_args, validate_encoding
from discovery.landmark import add_landmark_cli_args

from .queue import (
    claim_job,
    enqueue_jobs,
    load_job,
    mark_done,
    mark_failed,
    merge_job_args,
)

from .clinic import (
    DEFAULT_INNER_MODALITY,
    default_outer_modalities_for,
    evaluate_clinic_dir,
    ensure_modalities_allowed,
    parse_modalities,
    parse_one_modality,
)
from .data import default_analyzer_split_dir, load_candidate_fields, resolve_patient_universe
from .embeddings import subset_embedding_dir, subset_scheme_name
from .protocol import run_nested_greedy

from .clinic_evaluator import make_clinic_evaluator_factory
from .splits import load_analyzer_split_dir
from .stability import plot_selection_frequency, write_selection_frequency
from .stability import cindex_curve_frame, plot_cindex_curve, write_cindex_curve


def _json_dump(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=_json_default)
        f.write("\n")


def _json_default(obj):
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"not json serializable: {type(obj)}")


def _path_payload(path: list[dict]) -> list[dict]:
    rows = []
    for step in path:
        rows.append(
            {
                "step": step["step"],
                "added": step["added"],
                "added_idx": step["added_idx"],
                "delta_c": step["delta_c"],
                "c_index": step["c_index"],
                "c_index_std": step.get("c_index_std", 0.0),
                "subset": step["subset"],
                "subset_idx": step["subset_idx"],
                "all_candidates": {
                    name: {"c_index": vals["c_index"], "idx": vals["idx"]}
                    for name, vals in step.get("all_candidates", {}).items()
                },
            }
        )
    return rows


def _curve_payload(curve: list[dict]) -> list[dict]:
    rows = []
    for row in curve:
        rows.append(
            {
                "k": row["k"],
                "c_index_mean": row["c_index_mean"],
                "c_index_std": row["c_index_std"],
                "c_index_se": row["c_index_se"],
                "delta_mean": row["delta_mean"],
                "delta_p": row["delta_p"],
            }
        )
    return rows



def _resolve_init_idx(fields: list[str], raw: str | None) -> list[int]:
    names = _parse_init_fields(raw)
    if not names:
        return []
    by_name = {name: i for i, name in enumerate(fields)}
    by_leaf = {}
    for i, name in enumerate(fields):
        leaf = name.split(".")[-1].replace("[]", "")
        by_leaf.setdefault(leaf, []).append(i)
    idx = []
    seen = set()
    missing = []
    for name in names:
        if name.endswith(".") and name != ".":
            matched = [i for i, field in enumerate(fields) if field.startswith(name)]
            if not matched:
                missing.append(name)
                continue
            for chosen in matched:
                if chosen not in seen:
                    seen.add(chosen)
                    idx.append(chosen)
            continue
        if name in by_name:
            chosen = by_name[name]
        elif name in by_leaf and len(by_leaf[name]) == 1:
            chosen = by_leaf[name][0]
        elif name in by_leaf:
            missing.append(name)
            continue
        else:
            missing.append(name)
            continue
        if chosen not in seen:
            seen.add(chosen)
            idx.append(chosen)
    if missing:
        missing_text = ", ".join(missing)
        raise SystemExit(f"not found {missing_text} field")
    return idx


def _score_outer_modalities(
    *,
    dataset: str,
    path: list[dict],
    outer_modalities: list[str],
    inner_modality: str,
    work_dir: Path,
    split_dir: Path,
    args,
    n_folds: int,
) -> dict:
    scores = {}
    last = path[-1] if path else None
    if last is None:
        return scores
    subset_idx = list(last.get("subset_idx") or [])
    scheme = subset_scheme_name(subset_idx)
    from common.paths import PROJECT_ROOT
    encoding = validate_encoding(getattr(args, "encoding", "prompt"))
    clinic_dir = subset_embedding_dir(
        dataset,
        scheme,
        PROJECT_ROOT / "outputs",
        encoding=encoding,
        landmark_tag=getattr(args, "landmark_tag", None),
        experiment=getattr(args, "experiment", None),
    )
    for modality in outer_modalities:
        if modality == inner_modality and last.get("c_index") is not None:
            scores[modality] = {
                "c_index_mean": float(last["c_index"]),
                "c_index_std": float(last.get("c_index_std") or 0.0),
                "reused_inner": True,
            }
            continue
        payload = evaluate_clinic_dir(
            clinic_dir,
            dataset=dataset,
            scheme=scheme,
            modality=modality,
            exp_group=("longitudinal" if getattr(args, "experiment", None) else "greedy"),
            python_exe=args.analyzer_python,
            k=n_folds,
            k_start=0,
            k_end=n_folds,
            split_dir=split_dir,
            max_epochs=args.max_epochs,
            seed=args.seed,
            prefer_val=False,
            reuse=True,
            job_log=work_dir / "jobs" / f"{scheme}__{modality}.json",
        )
        scores[modality] = {
            "c_index_mean": payload.get("test_c_index_mean", payload.get("c_index_mean")),
            "c_index_std": payload.get("test_c_index_std", payload.get("c_index_std", 0.0)),
            "source": payload.get("source"),
            "results_dir": payload.get("results_dir"),
        }
    return scores

def make_clinic_factory(dataset: str, field_bank_dir: Path, work_dir: Path, args, split_dir: Path):
    return make_clinic_evaluator_factory(
        dataset=dataset,
        fields=list(args._fields),
        field_bank_dir=field_bank_dir,
        work_dir=work_dir,
        modality=args.inner_modality,
        max_epochs=args.max_epochs,
        conch_python=args.conch_python,
        analyzer_python=args.analyzer_python,
        extra_args=[],
        split_dir=split_dir,
        landmark_tag=getattr(args, "landmark_tag", None),
        experiment=getattr(args, "experiment", None),
        exp_group=("longitudinal" if getattr(args, "experiment", None) else "greedy"),
    )


def _parse_csv_list(raw: str) -> list[str]:
    return [item.strip() for item in str(raw).split(",") if item.strip()]


def _parse_init_fields(raw: str | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        parts = [str(x).strip() for x in raw if str(x).strip()]
        text = ",".join(parts)
    else:
        text = str(raw).strip()
    if not text:
        return []
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1].strip()
    return _parse_csv_list(text)


def _load_splits(args, dataset: str):
    if args.splits:
        split_path = Path(args.splits)
    else:
        split_path = default_analyzer_split_dir(dataset)
    if not split_path.exists():
        raise FileNotFoundError(
            f"未找到本地 5-fold splits: {split_path}。"
            "请确认 Clinic_Analyzer/data/splits/5foldcv 下对应 study 目录存在。"
        )
    if not split_path.is_dir():
        raise ValueError(f"--splits 必须是含 splits_*.csv 的目录，收到: {split_path}")
    splits = load_analyzer_split_dir(split_path)
    return splits, str(split_path.resolve())


def _write_run_outputs(out_dir: Path, dataset: str, fields, patient_ids, splits, result, args, split_source, started, inner_modality: str, outer_modalities: list[str]):
    path_payload = {
        "dataset": dataset,
        "encoding": getattr(args, "encoding", "prompt"),
        "inner_modality": inner_modality,
        "outer_modalities": list(outer_modalities),
        "n_fields": len(fields),
        "n_patients": len(patient_ids),
        "n_folds": result["n_folds"],
        "path": _path_payload(result.get("path") or []),
        "folds": [
            {
                "fold_id": rec["fold_id"],
                "repeat": rec["repeat"],
                "fold": rec["fold"],
                "n_train": rec["n_train"],
                "n_val": rec["n_val"],
                "n_test": rec["n_test"],
                "inner_path": _path_payload(rec["path"]),
                "outer_test": rec["test_details"],
                "empty_test_score": rec.get("empty_test_score"),
            }
            for rec in result["fold_records"]
        ],
        "curve": _curve_payload(result["stopping"]["curve"]),
        "points": result["points"],
    }
    _json_dump(out_dir / "path.json", path_payload)
    write_selection_frequency(result["selection_freq"], out_dir / "selection_freq.csv")
    heatmap = plot_selection_frequency(result["selection_freq"], out_dir / "selection_freq.png")
    curve_df = cindex_curve_frame(result.get("path") or [], result.get("stopping", {}).get("curve") or [])
    write_cindex_curve(curve_df, out_dir / "cindex_by_n_fields.csv")
    curve_png = plot_cindex_curve(curve_df, out_dir / "cindex_by_n_fields.png", points=result.get("points"))
    config = {
        "dataset": dataset,
        "inner_modality": inner_modality,
        "outer_modalities": list(outer_modalities),
        "init_field": getattr(args, "init_field", None),
        "outer_scores": result.get("outer_scores", {}),
        "seed": args.seed,
        "patience": args.patience,
        "min_delta": args.min_delta,
        "max_steps": args.max_steps,
        "exclude_post_baseline": bool(args.exclude_post_baseline),
        "n_fields": len(fields),
        "n_patients": len(patient_ids),
        "n_folds": result["n_folds"],
        "encoding": getattr(args, "encoding", "prompt"),
        "experiment": getattr(args, "experiment", None) or "",
        "landmark_tag": getattr(args, "landmark_tag", None),
        "field_bank_dir": str(Path(args.field_bank_dir) if args.field_bank_dir else dataset_field_bank_dir(dataset, getattr(args, "encoding", "prompt"), getattr(args, "landmark_tag", None), experiment=getattr(args, "experiment", None))),
        "kept_fields": args.kept_fields,
        "splits": split_source,
        "max_epochs": args.max_epochs,
        "conch_python": args.conch_python,
        "analyzer_python": args.analyzer_python,
        "elapsed_sec": timer() - started,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "points": result["points"],
    }
    _json_dump(out_dir / "run_config.json", config)
    print(f"\n######## Dataset: {dataset}  inner={inner_modality} ########")
    print(f"  patients={len(patient_ids)} fields={len(fields)} folds={result['n_folds']}")
    for name in ("best", "parsimonious", "sig_stop"):
        point = result["points"][name]
        print(f"  {name}: k={point['k']} c_index={point.get('c_index_mean')} subset={point.get('subset')}")
    print(f"  wrote {out_dir / 'selection_freq.csv'}")
    if heatmap is not None:
        print(f"  wrote {heatmap}")
    print(f"  wrote {out_dir / 'cindex_by_n_fields.csv'}")
    if curve_png is not None:
        print(f"  wrote {curve_png}")
    print(f"  elapsed={config['elapsed_sec']:.2f}s")


def run_one(args, dataset: str) -> Path:
    encoding = validate_encoding(getattr(args, "encoding", "prompt"))
    args.encoding = encoding
    tag = landmark_tag_from_args(args)
    args.landmark_tag = tag
    experiment = experiment_from_args(args)
    args.experiment = experiment
    if args.out:
        out_dir = Path(args.out)
        if getattr(args, "_multi_dataset", False):
            out_dir = out_dir / dataset / tag
    else:
        out_dir = dataset_greedy_dir(dataset, encoding, tag, experiment=experiment)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = timer()
    fields = load_candidate_fields(
        dataset,
        kept_fields_path=args.kept_fields,
        field_index_path=args.field_index,
        encoding=encoding,
        landmark_tag=tag,
        experiment=experiment,
    )
    if args.exclude_post_baseline:
        fields = [f for f in fields if "follow_ups" not in f and "other_clinical_attributes" not in f]

    args._fields = fields

    field_bank_dir = Path(args.field_bank_dir) if args.field_bank_dir else dataset_field_bank_dir(dataset, encoding, tag, experiment=experiment)
    patient_ids, events = resolve_patient_universe(
        dataset, field_bank_dir=field_bank_dir, label_file=args.label_file, encoding=encoding, landmark_tag=tag
    )

    splits, split_source = _load_splits(args, dataset)
    split_dir = Path(split_source)

    inner_modality = parse_one_modality(args.inner_modality)
    raw_outer = getattr(args, "outer_modalities", None)
    if raw_outer in (None, ""):
        outer_modalities = list(default_outer_modalities_for(dataset))
    else:
        outer_modalities = parse_modalities(raw_outer)
    ensure_modalities_allowed(dataset, [inner_modality, *outer_modalities])
    args.inner_modality = inner_modality
    factory = make_clinic_factory(dataset, field_bank_dir, out_dir, args, split_dir)
    init_idx = _resolve_init_idx(fields, getattr(args, "init_field", None))
    result = run_nested_greedy(
        factory,
        splits,
        fields=fields,
        max_steps=args.max_steps,
        patience=args.patience,
        seed=args.seed,
        init_idx=init_idx,
        workers=args.workers,
        min_delta=args.min_delta,
    )
    result["outer_scores"] = _score_outer_modalities(
        dataset=dataset,
        path=result.get("path") or [],
        outer_modalities=outer_modalities,
        inner_modality=inner_modality,
        work_dir=out_dir,
        split_dir=split_dir,
        args=args,
        n_folds=max(len(splits), 1),
    )
    _write_run_outputs(
        out_dir, dataset, fields, patient_ids, splits, result, args, split_source, started, inner_modality, outer_modalities
    )
    return out_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="5-fold greedy forward selection: slice Field Bank embeddings, "
        "run Clinic_Analyzer, then search on returned c-index."
    )
    parser.add_argument("--dataset", required=True, help="数据集名；支持 all 或逗号分隔列表。调度器按这个列表自动生成 conf，不用手写。")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument(
        "--kept_fields",
        default=None,
        help="覆盖默认 rawdata_stats/{dataset}/{landmark_tag}/kept_fields.json",
    )
    parser.add_argument("--field_index", default=None)
    parser.add_argument(
        "--encoding",
        default="prompt",
        choices=list(VALID_ENCODINGS),
    )
    parser.add_argument("--field_bank_dir", default=None)
    parser.add_argument(
        "--experiment",
        default="",
        help="空=默认 Field Bank 实验；longitudinal=走 outputs/{dataset}/longitudinal/...",
    )
    add_landmark_cli_args(parser, extraction=True)
    parser.add_argument("--label_file", default=None)
    parser.add_argument(
        "--splits",
        default=None,
        help="覆盖现成 splits 目录；默认读 Clinic_Analyzer/data/splits/5foldcv/{study}",
    )
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--init_field",
        default=None,
        nargs="+",
        help="贪婪起点字段，写在大括号里。family 前缀：--init_field '{demographic.}' 会展开成该 dataset Field Bank 里所有 demographic.* 字段；也可写完整路径：--init_field '{demographic.ethnicity,demographic.sex_at_birth}'",
    )
    parser.add_argument(
        "--inner_modality",
        default=DEFAULT_INNER_MODALITY,
        help="内层选字段只用一个 Clinic_Analyzer modality，默认 mlp_clinic_flatten",
    )
    parser.add_argument(
        "--outer_modalities",
        default=None,
        help="外层复评 greedy 路径的 modality 列表，逗号分隔；单模态默认 mlp/snn，多模态默认全部 Analyzer 模型",
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument(
        "--min_delta",
        type=float,
        default=0.0,
        help="内层 greedy 早停阈值：下一步最好字段的 c-index 增益小于该值时，不加该字段并停止。默认 0，即负增益就停。设为负数可接近关闭。",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="同一步内并行评估候选子集的进程数。只并行当前 greedy 步的候选，不拆整条路径。",
    )
    parser.add_argument("--max_steps", type=int, default=None)
    parser.add_argument("--exclude_post_baseline", action="store_true")
    parser.add_argument("--max_epochs", type=int, default=None)
    parser.add_argument("--conch_python", default="/data/fangyuxuan/miniconda3/envs/conch/bin/python")
    parser.add_argument("--analyzer_python", default="/data/fangyuxuan/miniconda3/envs/SurvPGC/bin/python")
    parser.add_argument(
        "--queue_root",
        default=None,
        help="greedy conf 队列根目录。默认 Clinic_Analyzer/configs/greedy/{queue,running,done,failed}",
    )
    return parser


def resolve_dataset_list(args) -> list[str]:
    datasets = load_dataset_configs(args.datasets_config)
    names = resolve_dataset_names(args.dataset, datasets)
    if not names:
        names = [args.dataset]
    return names


def run_claimed_jobs(args) -> None:
    names = resolve_dataset_list(args)
    queued = enqueue_jobs(args, names)
    root = queued["root"]
    job_key = queued["job_key"]
    print(
        f"[queue] root={root} job_key={job_key} "
        f"created={len(queued['created'])} existing={len(queued['existing'])}"
    )
    while True:
        claimed = claim_job(root, job_key)
        if claimed is None:
            print(f"[queue] idle job_key={job_key}")
            return
        job = load_job(claimed)
        dataset = job["dataset"]
        gpu = job.get("cuda_visible_devices") or os.environ.get("CUDA_VISIBLE_DEVICES", "")
        landmark = job.get("landmark_tag") or job.get("landmark_time") or ""
        print(f"[queue] claim {claimed.name} dataset={dataset} landmark={landmark} gpu={gpu}")
        job_args = merge_job_args(args, job)
        try:
            run_one(job_args, dataset)
        except Exception as exc:
            dest = mark_failed(claimed, error=f"{type(exc).__name__}: {exc}")
            print(f"[queue] fail {dest.name} dataset={dataset} landmark={landmark}: {exc}")
            continue
        dest = mark_done(claimed)
        print(f"[queue] done {dest.name} dataset={dataset} landmark={landmark}")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    names = resolve_dataset_list(args)
    args._multi_dataset = (
        len(names) > 1
        or str(args.dataset) == "all"
        or "," in str(args.landmark_time)
        or str(args.landmark_time).strip().lower() == "all"
    )
    run_claimed_jobs(args)
