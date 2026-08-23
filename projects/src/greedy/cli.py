"""CLI for the nested greedy scheduler."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from timeit import default_timer as timer

from common.datasets import load_dataset_configs, resolve_dataset_names
from common.paths import DEFAULT_DATASETS_CONFIG, dataset_field_bank_dir, dataset_greedy_dir

from .clinic import (
    DEFAULT_INNER_MODALITY,
    DEFAULT_OUTER_MODALITIES,
    evaluate_clinic_dir,
    parse_modalities,
    parse_one_modality,
)
from .data import default_survpgc_split_dir, load_candidate_fields, load_eligible_case_ids, resolve_patient_universe
from .embeddings import subset_embedding_dir, subset_scheme_name
from .protocol import run_nested_greedy

from .clinic_evaluator import make_clinic_evaluator_factory
from .splits import (
    NestedSplitConfig,
    build_nested_splits,
    load_analyzer_split_dir,
    load_nested_splits,
    save_nested_splits,
    write_analyzer_split_dir,
)
from .stability import plot_selection_frequency, write_selection_frequency


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
    clinic_dir = subset_embedding_dir(dataset, scheme, PROJECT_ROOT / "outputs")
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
            exp_group="greedy",
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


def _load_splits(args, dataset: str, patient_ids, events, out_dir: Path):
    source = str(getattr(args, "splits_source", "external") or "external").lower()
    if args.splits:
        split_path = Path(args.splits)
        if split_path.is_dir():
            splits = load_analyzer_split_dir(split_path)
        else:
            splits = load_nested_splits(split_path)
        return splits, str(split_path.resolve())
    if source == "internal":
        eligible = set(load_eligible_case_ids(dataset))
        keep_ids = [pid for pid in patient_ids if pid in eligible]
        if len(keep_ids) < int(args.outer_folds):
            raise ValueError(
                f"内部生成 fold 时，模态齐全患者不足 {args.outer_folds} 人：dataset={dataset}, n={len(keep_ids)}"
            )
        keep_events = {pid: events.get(pid, 0) for pid in keep_ids}
        split_cfg = NestedSplitConfig(
            outer_folds=args.outer_folds,
            repeats=args.repeats,
            seed=args.seed,
        )
        splits = build_nested_splits(keep_ids, events=keep_events, config=split_cfg)
        split_source = str(out_dir / "splits.json")
        save_nested_splits(split_source, splits, config=split_cfg)
        write_analyzer_split_dir(out_dir / "analyzer_splits", splits)
        return splits, split_source
    if source != "external":
        raise ValueError(f"--splits_source 只支持 external / internal，收到: {source}")
    split_path = default_survpgc_split_dir(dataset)
    if not split_path.exists():
        raise FileNotFoundError(
            f"未找到 SurvPGC 5-fold splits: {split_path}。"
            "请确认 SurvPGC_github_init/splits/5foldcv/{study} 存在，或改用 --splits_source internal。"
        )
    splits = load_analyzer_split_dir(split_path)
    return splits, str(split_path.resolve())


def _write_run_outputs(out_dir: Path, dataset: str, fields, patient_ids, splits, result, args, split_source, started, inner_modality: str, outer_modalities: list[str]):
    path_payload = {
        "dataset": dataset,
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
    config = {
        "dataset": dataset,
        "inner_modality": inner_modality,
        "outer_modalities": list(outer_modalities),
        "init_field": getattr(args, "init_field", None),
        "splits_source": getattr(args, "splits_source", "external"),
        "outer_scores": result.get("outer_scores", {}),
        "outer_folds": args.outer_folds,
        "repeats": args.repeats,
        "seed": args.seed,
        "patience": args.patience,
        "max_steps": args.max_steps,
        "exclude_post_baseline": bool(args.exclude_post_baseline),
        "n_fields": len(fields),
        "n_patients": len(patient_ids),
        "n_folds": result["n_folds"],
        "field_bank_dir": str(Path(args.field_bank_dir) if args.field_bank_dir else dataset_field_bank_dir(dataset)),
        "active_fields": args.active_fields,
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
    print(f"  elapsed={config['elapsed_sec']:.2f}s")


def run_one(args, dataset: str) -> Path:
    if args.out:
        out_dir = Path(args.out)
        if getattr(args, "_multi_dataset", False):
            out_dir = out_dir / dataset
    else:
        out_dir = dataset_greedy_dir(dataset)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = timer()

    fields = load_candidate_fields(
        dataset,
        active_fields_path=args.active_fields,
        field_index_path=args.field_index,
    )
    if args.exclude_post_baseline:
        fields = [f for f in fields if "follow_ups" not in f and "other_clinical_attributes" not in f]

    args._fields = fields

    field_bank_dir = Path(args.field_bank_dir) if args.field_bank_dir else dataset_field_bank_dir(dataset)
    patient_ids, events = resolve_patient_universe(
        dataset, field_bank_dir=field_bank_dir, label_file=args.label_file
    )

    splits, split_source = _load_splits(args, dataset, patient_ids, events, out_dir)
    split_dir = Path(split_source)

    inner_modality = parse_one_modality(args.inner_modality)
    outer_modalities = parse_modalities(args.outer_modalities)
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


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="5-fold greedy forward selection: slice Field Bank embeddings, "
        "run Clinic_Analyzer, then search on returned c-index."
    )
    parser.add_argument("--dataset", required=True, help="数据集名；支持 all 或逗号分隔列表")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument(
        "--active_fields",
        default=None,
        help="覆盖默认 rawdata_stats/{dataset}/fliter_log/active_fields.json",
    )
    parser.add_argument("--field_index", default=None)
    parser.add_argument("--field_bank_dir", default=None)
    parser.add_argument("--label_file", default=None)
    parser.add_argument(
        "--splits_source",
        choices=("external", "internal"),
        default="external",
        help="external=读取 SurvPGC 5foldcv；internal=按 SurvPGC split_eligibility.csv 的齐全患者内部划 fold",
    )
    parser.add_argument(
        "--splits",
        default=None,
        help="覆盖 splits 目录或 splits.json；提供后不再使用 --splits_source",
    )
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--init_field",
        default=None,
        nargs="+",
        help="贪婪起点字段，使用 FIELD_BANK.csv 的 field 路径。多个字段请加引号：--init_field '{demographic.ethnicity,demographic.sex_at_birth}'",
    )
    parser.add_argument(
        "--inner_modality",
        default=DEFAULT_INNER_MODALITY,
        help="内层选字段只用一个 Clinic_Analyzer modality，默认 mlp_clinic_flatten",
    )
    parser.add_argument(
        "--outer_modalities",
        default=",".join(DEFAULT_OUTER_MODALITIES),
        help="外层复评 greedy 路径的 modality 列表，逗号分隔；默认 mlp/snn 的 mean 与 flatten",
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--outer_folds", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--patience", type=int, default=3)
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
    args = parser.parse_args(argv)

    datasets = load_dataset_configs(args.datasets_config)
    names = resolve_dataset_names(args.dataset, datasets)
    if not names:
        names = [args.dataset]
    args._multi_dataset = len(names) > 1
    for name in names:
        run_one(args, name)
