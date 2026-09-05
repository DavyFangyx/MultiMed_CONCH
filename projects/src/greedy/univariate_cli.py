"""CLI for univariate Field Bank c-index evaluation."""

from __future__ import annotations

import argparse
import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from timeit import default_timer as timer

from common.datasets import load_dataset_configs, resolve_dataset_names
from common.paths import (
    DEFAULT_DATASETS_CONFIG,
    PROJECT_ROOT,
    VALID_ENCODINGS,
    dataset_field_bank_dir,
    dataset_univariate_dir,
    experiment_from_args,
    landmark_tag_from_args,
    validate_encoding,
)
from discovery.landmark import add_landmark_cli_args

from .clinic import DEFAULT_INNER_MODALITY, ensure_modalities_allowed, parse_one_modality
from .clinic_evaluator import DEFAULT_CONCH_PYTHON, DEFAULT_SURVPGC_PYTHON, ClinicSubsetEvaluator
from .data import default_analyzer_split_dir, load_candidate_fields, load_field_bank
from .embeddings import subset_embedding_dir, subset_scheme_name
from .queue import (
    claim_job,
    enqueue_jobs,
    load_job,
    mark_done,
    mark_failed,
    merge_job_args,
)
from .splits import load_analyzer_split_dir


CSV_COLUMNS = [
    "field",
    "field_idx",
    "n_fields",
    "c_index_mean",
    "c_index_std",
    "per_fold",
    "status",
]


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


def _short_error(exc: BaseException, limit: int = 240) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _json_list(values) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _ok_row(field: str, field_idx: int, result: dict) -> dict:
    per_fold = result.get("per_fold") or []
    return {
        "field": field,
        "field_idx": int(field_idx),
        "n_fields": 1,
        "c_index_mean": result.get("c_index_mean"),
        "c_index_std": result.get("c_index_std", 0.0),
        "per_fold": _json_list(per_fold),
        "status": "ok",
        "scheme": result.get("scheme") or subset_scheme_name([field_idx]),
        "clinic_dir": result.get("clinic_dir") or "",
        "error": "",
    }


def _error_row(field: str, field_idx: int, exc: BaseException, *, scheme: str = "", clinic_dir: str = "") -> dict:
    return {
        "field": field,
        "field_idx": int(field_idx),
        "n_fields": 1,
        "c_index_mean": "",
        "c_index_std": "",
        "per_fold": "",
        "status": "error",
        "scheme": scheme,
        "clinic_dir": clinic_dir,
        "error": _short_error(exc),
    }


def sort_field_rows(rows: list[dict]) -> list[dict]:
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    err_rows = [row for row in rows if row.get("status") != "ok"]
    ok_rows.sort(key=lambda row: (-float(row["c_index_mean"]), int(row["field_idx"])))
    err_rows.sort(key=lambda row: int(row["field_idx"]))
    return ok_rows + err_rows


def field_error_payload(rows: list[dict]) -> list[dict]:
    payload = []
    for row in rows:
        if row.get("status") != "error":
            continue
        payload.append(
            {
                "field": row.get("field"),
                "field_idx": row.get("field_idx"),
                "error": row.get("error") or "",
                "scheme": row.get("scheme") or "",
                "clinic_dir": row.get("clinic_dir") or "",
            }
        )
    return payload


def write_field_cindex_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            payload = {}
            for key in CSV_COLUMNS:
                value = row.get(key, "")
                payload[key] = "" if value is None else value
            writer.writerow(payload)


def evaluate_one_field(evaluator, field_idx: int, field_name: str, *, embeddings_root: Path | None = None, encoding: str = "prompt") -> dict:
    scheme = subset_scheme_name([field_idx])
    clinic_dir = ""
    if embeddings_root is not None:
        clinic_dir = str(
            subset_embedding_dir(
                getattr(evaluator, "dataset", ""),
                scheme,
                embeddings_root,
                encoding=encoding,
                landmark_tag=getattr(evaluator, "landmark_tag", None),
                experiment=getattr(evaluator, "experiment", None),
            )
        )
    try:
        result = evaluator.evaluate([field_idx])
        if result.get("empty"):
            raise RuntimeError("empty subset is not a univariate row")
        row = _ok_row(field_name, field_idx, result)
        if not row["clinic_dir"]:
            row["clinic_dir"] = clinic_dir
        return row
    except Exception as exc:
        return _error_row(field_name, field_idx, exc, scheme=scheme, clinic_dir=clinic_dir)


def evaluate_all_fields(
    evaluator,
    fields: list[str],
    *,
    workers: int = 8,
    embeddings_root: Path | None = None,
    encoding: str = "prompt",
) -> list[dict]:
    indexed = list(enumerate(fields))
    rows: list[dict | None] = [None] * len(fields)
    n_workers = max(int(workers or 1), 1)

    def _run(item):
        field_idx, field_name = item
        return field_idx, evaluate_one_field(
            evaluator,
            field_idx,
            field_name,
            embeddings_root=embeddings_root,
            encoding=encoding,
        )

    if n_workers == 1 or len(fields) <= 1:
        scored = [_run(item) for item in indexed]
    else:
        scored = []
        with ThreadPoolExecutor(max_workers=min(n_workers, len(fields))) as pool:
            futures = [pool.submit(_run, item) for item in indexed]
            for fut in as_completed(futures):
                scored.append(fut.result())
    for field_idx, row in scored:
        rows[field_idx] = row
    return sort_field_rows([row for row in rows if row is not None])


def write_univariate_outputs(
    out_dir: Path,
    rows: list[dict],
    *,
    dataset: str,
    encoding: str,
    modality: str,
    workers: int,
    seed: int,
    field_bank_dir: Path | str,
    split_dir: Path | str,
    extra: dict | None = None,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_field_cindex_csv(out_dir / "field_cindex.csv", rows)
    config = {
        "dataset": dataset,
        "encoding": encoding,
        "modality": modality,
        "n_fields": len(rows),
        "n_ok": sum(1 for row in rows if row.get("status") == "ok"),
        "n_error": sum(1 for row in rows if row.get("status") == "error"),
        "workers": int(workers),
        "seed": int(seed),
        "prefer_val": True,
        "field_bank_dir": str(field_bank_dir),
        "split_dir": str(split_dir),
        "out_dir": str(out_dir),
        "field_errors": field_error_payload(rows),
    }
    if extra:
        config.update(extra)
    _json_dump(out_dir / "run_config.json", config)
    return config


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate each Field Bank field as a singleton clinic model and report 5-fold val c-index."
    )
    parser.add_argument("--dataset", required=True, help="数据集名；支持 all 或逗号分隔列表。调度器按这个列表自动生成 conf，不用手写。")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
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
    parser.add_argument(
        "--field_index",
        default=None,
        help="覆盖 Field Bank 的 field_index.json；字段名和顺序以它为准",
    )
    parser.add_argument(
        "--splits",
        default=None,
        help="覆盖现成 splits 目录；默认读 Clinic_Analyzer/data/splits/5foldcv/{study}",
    )
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--modality",
        default=DEFAULT_INNER_MODALITY,
        help="只允许一个 clinic 模型，默认 mlp_clinic_flatten",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="并行评字段，不是并行 fold。默认 8。",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max_epochs", type=int, default=None)
    parser.add_argument("--conch_python", default=str(DEFAULT_CONCH_PYTHON))
    parser.add_argument("--analyzer_python", default=str(DEFAULT_SURVPGC_PYTHON))
    parser.add_argument(
        "--queue_root",
        default=None,
        help="univariate conf 队列根目录。默认 Clinic_Analyzer/configs/univariate/{queue,running,done,failed}",
    )
    parser.set_defaults(queue_kind="univariate")
    return parser


def _load_splits(args, dataset: str):
    split_path = Path(args.splits) if args.splits else default_analyzer_split_dir(dataset)
    if not split_path.exists():
        raise FileNotFoundError(
            f"未找到本地 5-fold splits: {split_path}。"
            "请确认 Clinic_Analyzer/data/splits/5foldcv 下对应 study 目录存在。"
        )
    if not split_path.is_dir():
        raise ValueError(f"--splits 必须是含 splits_*.csv 的目录，收到: {split_path}")
    splits = load_analyzer_split_dir(split_path)
    return splits, split_path.resolve()


def _require_field_bank(field_bank_dir: Path, encoding: str) -> dict:
    if not field_bank_dir.exists():
        raise FileNotFoundError(f"field bank not found: {field_bank_dir}")
    loaded = load_field_bank(field_bank_dir, encoding=encoding)
    index_path = loaded["dir"] / "field_index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"field_index.json not found: {index_path}")
    pt_dir = loaded["pt_dir"]
    pt_files = list(pt_dir.glob("*.pt")) if pt_dir.is_dir() else []
    if not pt_files:
        raise FileNotFoundError(f"no Field Bank .pt files under {pt_dir}")
    return loaded


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
        out_dir = dataset_univariate_dir(dataset, encoding, tag, experiment=experiment)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = timer()

    field_bank_dir = Path(args.field_bank_dir) if args.field_bank_dir else dataset_field_bank_dir(dataset, encoding, tag, experiment=experiment)
    loaded = _require_field_bank(field_bank_dir, encoding)
    field_index_path = Path(args.field_index) if args.field_index else loaded["dir"] / "field_index.json"
    fields = load_candidate_fields(dataset, field_index_path=field_index_path)
    if not fields:
        raise ValueError(f"field_index has no fields: {field_index_path}")

    splits, split_dir = _load_splits(args, dataset)
    modality = parse_one_modality(args.modality)
    ensure_modalities_allowed(dataset, [modality])

    evaluator = ClinicSubsetEvaluator(
        dataset=dataset,
        fields=fields,
        splits=splits,
        field_bank_dir=field_bank_dir,
        work_dir=out_dir,
        modality=modality,
        seed=args.seed,
        for_test=False,
        max_epochs=args.max_epochs,
        conch_python=args.conch_python,
        analyzer_python=args.analyzer_python,
        split_dir=split_dir,
        landmark_tag=tag,
        experiment=experiment,
        exp_group=("longitudinal" if experiment else "greedy"),
    )
    rows = evaluate_all_fields(
        evaluator,
        fields,
        workers=args.workers,
        embeddings_root=PROJECT_ROOT / "outputs",
        encoding=encoding,
    )
    config = write_univariate_outputs(
        out_dir,
        rows,
        dataset=dataset,
        encoding=encoding,
        modality=modality,
        workers=args.workers,
        seed=args.seed,
        field_bank_dir=field_bank_dir,
        split_dir=split_dir,
        extra={
            "elapsed_sec": timer() - started,
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n_patients": len(list(loaded["pt_dir"].glob("*.pt"))),
            "experiment": experiment,
            "landmark_tag": tag,
        },
    )
    print(f"\n######## Dataset: {dataset}  univariate {encoding} {modality} ########")
    print(f"  fields={config['n_fields']} ok={config['n_ok']} error={config['n_error']}")
    print(f"  wrote {out_dir / 'field_cindex.csv'}")
    print(f"  wrote {out_dir / 'run_config.json'}")
    return out_dir


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
    parser = make_parser()
    args = parser.parse_args(argv)
    args.queue_kind = "univariate"
    names = resolve_dataset_list(args)
    args._multi_dataset = (
        len(names) > 1
        or str(args.dataset) == "all"
        or "," in str(args.landmark_time)
        or str(args.landmark_time).strip().lower() == "all"
    )
    run_claimed_jobs(args)


if __name__ == "__main__":
    main()
