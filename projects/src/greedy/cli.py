"""CLI for the nested greedy scheduler."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from timeit import default_timer as timer

from common.datasets import load_dataset_configs, resolve_dataset_names
from common.paths import DEFAULT_DATASETS_CONFIG, REGISTRY_DIR, dataset_field_bank_dir, dataset_greedy_dir

from .data import load_candidate_fields, resolve_patient_universe
from .evaluator import StubEvaluator
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


def make_stub_factory(fields: list[str], noise: float = 0.01):
    def factory(split, seed=0, for_test=False):
        return StubEvaluator(fields, split=split, noise=0.0 if not for_test else noise)

    return factory


def make_clinic_factory(dataset: str, field_bank_dir: Path, work_dir: Path, args):
    return make_clinic_evaluator_factory(
        dataset=dataset,
        fields=list(args._fields),
        field_bank_dir=field_bank_dir,
        work_dir=work_dir,
        model=args.model,
        mode=args.mode,
        max_epochs=args.max_epochs,
        conch_python=args.conch_python,
        analyzer_python=args.analyzer_python,
        extra_args=[],
    )


def _parse_csv_list(raw: str) -> list[str]:
    return [item.strip() for item in str(raw).split(",") if item.strip()]


def _load_splits(args, patient_ids, events, out_dir: Path):
    split_cfg = NestedSplitConfig(
        outer_folds=args.outer_folds,
        repeats=args.repeats,
        seed=args.seed,
    )
    if args.splits:
        split_path = Path(args.splits)
        if split_path.is_dir():
            splits = load_analyzer_split_dir(split_path)
        else:
            splits = load_nested_splits(split_path)
        return splits, str(split_path.resolve())
    splits = build_nested_splits(patient_ids, events=events, config=split_cfg)
    split_source = str(out_dir / "splits.json")
    save_nested_splits(split_source, splits, config=split_cfg)
    write_analyzer_split_dir(out_dir / "analyzer_splits", splits)
    return splits, split_source


def _write_run_outputs(out_dir: Path, dataset: str, fields, patient_ids, splits, result, args, split_source, started, model: str, mode: str):
    path_payload = {
        "dataset": dataset,
        "model": model,
        "mode": mode,
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
        "evaluator": args.evaluator,
        "model": model,
        "mode": mode,
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
    print(f"\n######## Dataset: {dataset}  model={model} mode={mode} ########")
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

    splits, split_source = _load_splits(args, patient_ids, events, out_dir)

    models = _parse_csv_list(args.model) or ["mlp"]
    modes = _parse_csv_list(args.mode) or ["mean"]
    for model in models:
        for mode in modes:
            model_out = out_dir if len(models) == 1 and len(modes) == 1 else (out_dir / f"{model}_{mode}")
            model_out.mkdir(parents=True, exist_ok=True)
            args.model = model
            args.mode = mode
            if args.evaluator == "stub":
                factory = make_stub_factory(fields, noise=args.stub_noise)
            else:
                factory = make_clinic_factory(dataset, field_bank_dir, model_out, args)
            result = run_nested_greedy(
                factory,
                splits,
                fields=fields,
                max_steps=args.max_steps,
                patience=args.patience,
                seed=args.seed,
            )
            _write_run_outputs(
                model_out, dataset, fields, patient_ids, splits, result, args, split_source, started, model, mode
            )
    return out_dir


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="5-fold greedy forward selection: slice Field Bank embeddings, "
        "run Clinic_Analyzer, then search on returned c-index."
    )
    parser.add_argument("--dataset", required=True, help="数据集名；支持 all 或逗号分隔列表")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument("--active_fields", default=str(REGISTRY_DIR / "active_fields.json"))
    parser.add_argument("--field_index", default=None)
    parser.add_argument("--field_bank_dir", default=None)
    parser.add_argument("--label_file", default=None)
    parser.add_argument("--splits", default=None, help="复用已有 splits.json 或 Clinic_Analyzer splits 目录")
    parser.add_argument("--out", default=None)
    parser.add_argument("--evaluator", choices=("clinic", "stub"), default="clinic")
    parser.add_argument("--model", default="mlp", help="mlp / snn，逗号分隔则逐个模型各跑一条贪心")
    parser.add_argument("--mode", default="mean", help="mean / flatten，逗号分隔则逐个 pooling 各跑一条贪心")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--outer_folds", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--max_steps", type=int, default=None)
    parser.add_argument("--stub_noise", type=float, default=0.01)
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
