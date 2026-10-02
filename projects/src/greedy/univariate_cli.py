"""CLI for univariate Field Bank c-index evaluation."""

from __future__ import annotations

import argparse
import copy
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
    LANDMARK_OFF_TAG,
    PROJECT_ROOT,
    RESULTS_ROOT,
    VALID_ENCODINGS,
    dataset_field_bank_dir,
    dataset_univariate_dir,
    dataset_univariate_results_dir,
    experiment_from_args,
    landmark_tag_from_args,
    require_landmark_tag,
    resolve_cli_out_dir,
    test_results_dir,
    validate_encoding,
)
from discovery.landmark import add_landmark_cli_args

from .clinic import DEFAULT_INNER_MODALITY, ensure_modalities_allowed, parse_modalities, parse_one_modality
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
        "--field_bank_root",
        default=None,
        help="非规范 field bank 根目录：按 {root}/{dataset}/field_bank/{encoding}/{landmark_tag} 解析；"
        "Test_1a off 臂（raw 变体）用它指向 outputs/_raw。默认 None（走 outputs/{dataset}/field_bank/...）",
    )
    parser.add_argument(
        "--embeddings_root",
        default=None,
        help="subset embeddings 根目录（outputs/{dataset}/greedy/{encoding}/{tag}/subsets/...）；默认 outputs/。"
        "Test_1a off 臂用 outputs/_raw 与 t0 臂隔离。",
    )
    parser.add_argument(
        "--results_dir",
        default=None,
        help="Clinic_Analyzer 结果根目录（results/ 的替身）；默认 None（=results/）。"
        "Test_1a off 臂用 results/Test_1a/arm_off 避免污染 t0 的 results/Test_1a/arm_t0/。",
    )
    parser.add_argument(
        "--extraction_mask",
        default="auto",
        choices=["auto", "on", "off"],
        help="字段取值提取时的患者级 t0 mask 状态：auto=跟随 --landmark_time（天数=on，none=off）；"
        "off（raw 臂）=显式声明 mask 关闭，要求 field bank 的 landmark_policy=off 且必须用 --label_tag/--label_file 声明患者集",
    )
    parser.add_argument(
        "--label_tag",
        default=None,
        help="患者集（S4 派生 label {study}__{label_tag}.csv）使用的 landmark tag；默认跟随 --landmark_time。"
        "Test_1a off 臂用 --label_tag landmark_0 保证与 t0 臂同患者集。",
    )
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
    parser.add_argument(
        "--label_file",
        default=None,
        help="显式覆盖 label 文件；默认不传，由 --landmark_labels_dir/{study}__{tag}.csv 派生（见 --landmark_labels_dir）",
    )
    parser.add_argument(
        "--landmark_labels_dir",
        default=str(test_results_dir("Test_2b/arm_B") / "labels"),
        help="S4 派生的 landmark label 目录（{study}__landmark_{T}.csv，含经典三要件风险集排除）。"
        "开启 landmark（landmark_time 为天数）时强制使用，保证与 Test_1b 臂 B 同患者集。",
    )
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--analyzer",
        default=DEFAULT_INNER_MODALITY,
        help="clinic analyzer，逗号分隔；每个 analyzer 独立生成队列 conf 与结果目录。默认 mlp_clinic_flatten",
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
        help="univariate conf 队列根目录。默认 Clinic_Analyzer/configs/Test_1a_t0/{queue,running,done,failed}",
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


def resolve_extraction_mask(args, tag: str) -> str:
    """Field Bank 取值 mask 状态：'on'（landmark_{T} 取 t_hi<=T）或 'off'（raw，取值全集）。

    auto（默认）= 跟随 --landmark_time 推出的 tag；显式 on/off 必须与 tag 自洽。
    Test_1a off 臂用 --landmark_time none --extraction_mask off（field bank 由 mask off 提取）。
    """
    requested = str(getattr(args, "extraction_mask", "auto") or "auto").strip().lower()
    if requested not in {"auto", "on", "off"}:
        raise ValueError(f"--extraction_mask 只能是 auto/on/off，收到 {requested!r}")
    derived = "off" if tag == LANDMARK_OFF_TAG else "on"
    if requested == "auto":
        return derived
    if requested != derived:
        raise ValueError(
            f"--extraction_mask {requested} 与 --landmark_time 推出的 tag {tag} 冲突："
            f"mask {'关闭' if requested == 'off' else '开启'}需要 "
            f"--landmark_time {'none' if requested == 'off' else '天数'}"
        )
    return requested


def resolve_patient_label_tag(args, tag: str, mask_state: str) -> str:
    """患者集（S4 派生 label）使用的 landmark tag。

    raw 臂（--extraction_mask off）必须显式声明患者集来源，否则会退回全患者集、
    与 t0 臂不同患者集（Test_1a 两臂同患者集是硬要求）。
    """
    label_tag = str(getattr(args, "label_tag", "") or "").strip() or tag
    require_landmark_tag(label_tag)
    requested = str(getattr(args, "extraction_mask", "auto") or "auto").strip().lower()
    if mask_state == "off" and requested == "off":
        if label_tag == LANDMARK_OFF_TAG and not getattr(args, "label_file", None):
            raise ValueError(
                "--extraction_mask off（raw 臂）必须显式声明患者集：--label_tag landmark_0"
                "（S4 派生 label，与 t0 臂同患者集）或 --label_file。"
                "否则 mask 关闭会退回全患者集，两臂患者集不一致。"
            )
    return label_tag


def resolve_field_bank_dir(args, dataset: str, encoding: str, tag: str, experiment: str) -> Path:
    """--field_bank_dir（直接路径）> --field_bank_root（按 {root}/{dataset}/field_bank/{encoding}/{tag} 解析）> 规范路径。"""
    explicit = getattr(args, "field_bank_dir", None)
    if explicit:
        return Path(explicit)
    root = getattr(args, "field_bank_root", None)
    if root:
        return Path(root) / dataset / "field_bank" / validate_encoding(encoding) / require_landmark_tag(tag)
    return dataset_field_bank_dir(dataset, encoding, tag, experiment=experiment)


def resolve_embeddings_root(args) -> Path:
    raw = getattr(args, "embeddings_root", None)
    return Path(raw) if raw else PROJECT_ROOT / "outputs"


def resolve_results_root(args) -> Path | None:
    raw = getattr(args, "results_dir", None)
    return Path(raw) if raw else None


def assert_field_bank_mask(field_bank_dir: Path, mask_state: str, index: dict | None) -> None:
    """防止把 raw 臂指向 mask 开着的 field bank（或反之）——取值 mask 是 Test_1a 的唯一控制变量。"""
    policy = str((index or {}).get("landmark_policy") or "").strip()
    if not policy:
        return
    if mask_state == "off" and policy != "off":
        raise ValueError(
            f"--extraction_mask off 需要 mask 关闭（landmark_policy=off）的 field bank，"
            f"但 {field_bank_dir} 的 landmark_policy={policy}"
        )
    if mask_state == "on" and policy == "off":
        raise ValueError(
            f"--extraction_mask on 与 mask 关闭的 field bank 冲突：{field_bank_dir} 的 landmark_policy=off"
        )


def resolve_univariate_label_file(args, split_dir: Path, tag: str) -> str | None:
    """landmark 开启时强制使用 S4 派生的 {study}__landmark_{T}.csv（经典三要件风险集排除），
    保证 univariate 与 Test_1b 臂 B / 未来 Test_1c 同患者集。landmark_none（static_only）不用派生 label。"""
    if getattr(args, "label_file", None):
        path = Path(args.label_file)
        if not path.exists():
            raise FileNotFoundError(f"--label_file 不存在: {path}")
        return str(path)
    if tag == "landmark_none":
        return None
    labels_dir = Path(getattr(args, "landmark_labels_dir", None) or "")
    candidate = labels_dir / f"{split_dir.name}__{tag}.csv"
    if not candidate.exists():
        raise FileNotFoundError(
            f"未找到 landmark 派生 label: {candidate}。"
            "univariate 必须与 Test_1b 臂 B 同患者集（S4 派生 label，经典三要件风险集排除）。"
            "请确认 results/Test_2b/arm_B/labels/ 下该文件存在（可用 A_pipeline 的 "
            "landmark_labels 派生），或显式传 --label_file。"
        )
    return str(candidate)


def univariate_out_dir(args, dataset: str, encoding: str, landmark_tag: str, experiment: str, modality: str) -> Path:
    default_dir = dataset_univariate_results_dir(dataset, encoding, landmark_tag, experiment=experiment) / modality
    out_dir = resolve_cli_out_dir(args, default_dir, dataset, landmark_tag)
    if getattr(args, "out", None):
        out_dir = out_dir / modality  # 自定义 --out 不含 analyzer 层
    elif getattr(args, "results_dir", None):
        # --results_dir 是 results/ 的替身（Test_1a off 臂 = results/Test_1a/arm_off）：
        # 把 {results}/{exp_name}/{encoding}/{tag}/{ds}/{modality} 整体搬到 {results_dir}/ 下，
        # 与 analyzer 树（results_dir/univariate/.../{ds}/runs/...）同根对齐。
        try:
            rel = out_dir.relative_to(RESULTS_ROOT)
        except ValueError:
            rel = out_dir
        out_dir = Path(args.results_dir) / rel
    return out_dir


def run_one(args, dataset: str) -> Path:
    encoding = validate_encoding(getattr(args, "encoding", "prompt"))
    args.encoding = encoding
    tag = landmark_tag_from_args(args)
    args.landmark_tag = tag
    experiment = experiment_from_args(args)
    args.experiment = experiment
    mask_state = resolve_extraction_mask(args, tag)
    label_tag = resolve_patient_label_tag(args, tag, mask_state)
    embeddings_root = resolve_embeddings_root(args)
    results_root = resolve_results_root(args)
    modality = parse_one_modality(args.analyzer)
    ensure_modalities_allowed(dataset, [modality])
    work_dir = dataset_univariate_dir(dataset, encoding, tag, experiment=experiment)
    out_dir = univariate_out_dir(args, dataset, encoding, tag, experiment, modality)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = timer()

    field_bank_dir = resolve_field_bank_dir(args, dataset, encoding, tag, experiment)
    loaded = _require_field_bank(field_bank_dir, encoding)
    assert_field_bank_mask(field_bank_dir, mask_state, loaded.get("index"))
    field_index_path = Path(args.field_index) if args.field_index else loaded["dir"] / "field_index.json"
    fields = load_candidate_fields(dataset, field_index_path=field_index_path)
    if not fields:
        raise ValueError(f"field_index has no fields: {field_index_path}")

    splits, split_dir = _load_splits(args, dataset)
    label_file = resolve_univariate_label_file(args, split_dir, label_tag)

    evaluator = ClinicSubsetEvaluator(
        dataset=dataset,
        fields=fields,
        splits=splits,
        field_bank_dir=field_bank_dir,
        embeddings_root=embeddings_root,
        work_dir=work_dir,
        modality=modality,
        seed=args.seed,
        for_test=False,
        max_epochs=args.max_epochs,
        conch_python=args.conch_python,
        analyzer_python=args.analyzer_python,
        split_dir=split_dir,
        landmark_tag=tag,
        experiment=experiment,
        exp_group="univariate",
        label_file=label_file,
        results_dir_base=results_root,
    )
    rows = evaluate_all_fields(
        evaluator,
        fields,
        workers=args.workers,
        embeddings_root=embeddings_root,
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
            "label_file": label_file,
            "label_tag": label_tag,
            "extraction_mask": mask_state,
            "embeddings_root": str(embeddings_root),
            "results_dir_base": str(results_root) if results_root else "",
            "work_dir": str(work_dir),
            "results_dir": str(out_dir),
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
    names = [name for name in names if name and str(name).strip()]
    if not names:
        raise ValueError("--dataset 解析结果为空（shell 变量未定义时会展开成空串）；请检查 --dataset 取值")
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


def expand_analyzer_args(args):
    expanded = []
    for analyzer in parse_modalities(args.analyzer):
        analyzer_args = copy.copy(args)
        analyzer_args.analyzer = analyzer
        expanded.append(analyzer_args)
    return expanded


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
    for analyzer_args in expand_analyzer_args(args):
        run_claimed_jobs(analyzer_args)


if __name__ == "__main__":
    main()
