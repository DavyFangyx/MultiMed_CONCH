"""Enqueue A_manual embeddings into Clinic_Analyzer run.sh snapshots and write c-index tables."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import time
from pathlib import Path

from greedy.clinic import (
    DEFAULT_INNER_MODALITY,
    MULTIMODAL_DISPLAY,
    MULTIMODAL_MODALITIES,
    MULTIMODAL_STUDIES,
    parse_modalities,
    read_cindex,
    results_dir,
)
from greedy.data import DEFAULT_ANALYZER_SPLIT_ROOT, display_to_study

from .baseline import DEFAULT_BASELINE_SCHEMES, resolve_baseline_schemes
from .config import D_SCHEME_BY_TEXT_SCHEME, DEFAULT_TEXT_SCHEMES, PAPER_SCHEMES, resolve_scheme_names, schemes_for_dataset
from .paths import PROJECT_ROOT, dataset_baseline_embedding_dir, dataset_embedding_dir


DEFAULT_ANALYZER_MODALITY = DEFAULT_INNER_MODALITY
DEFAULT_RESULTS_ROOT = PROJECT_ROOT / "results"
DEFAULT_EXP_GROUP = "A_manual"
ANALYZER_EXP_GROUP = f"{DEFAULT_EXP_GROUP}/runs"
DEFAULT_QUEUE_ROOT = PROJECT_ROOT / "Clinic_Analyzer" / "configs" / "A_manual"
DEFAULT_ANALYZER_DIR = PROJECT_ROOT / "Clinic_Analyzer"
QUEUE_BUCKETS = ("queue", "running", "done", "failed")


def resolve_cindex_schemes(scheme: str, encoding: str) -> list[str]:
    encoding = str(encoding or "all").strip().lower()
    if encoding not in {"all", "text", "baseline"}:
        raise ValueError(f"unsupported cindex encoding: {encoding}")
    try:
        return resolve_scheme_names(scheme)
    except ValueError:
        if encoding == "text":
            raise
        return resolve_baseline_schemes(scheme)


def bound_scheme_name(scheme: str) -> str:
    if scheme.startswith("baseline__"):
        return scheme.split("__", 1)[1]
    return scheme


def expand_cindex_jobs(schemes: list[str], encoding: str) -> list[dict[str, str]]:
    encoding = str(encoding or "all").strip().lower()
    jobs = []
    seen = set()
    for scheme in schemes:
        name = bound_scheme_name(scheme)
        candidates = []
        if name in DEFAULT_TEXT_SCHEMES:
            if encoding in {"all", "text"}:
                candidates.append({"encoding": "prompt", "scheme": name, "bound_scheme": name})
            if encoding in {"all", "baseline"}:
                d_name = D_SCHEME_BY_TEXT_SCHEME[name]
                candidates.append({"encoding": "baseline", "scheme": d_name, "bound_scheme": name})
        elif name in DEFAULT_BASELINE_SCHEMES:
            if encoding in {"all", "baseline"}:
                candidates.append({"encoding": "baseline", "scheme": name, "bound_scheme": name})
        elif name in PAPER_SCHEMES:
            if encoding in {"all", "text"}:
                candidates.append({"encoding": "prompt", "scheme": name, "bound_scheme": name})
            if encoding in {"all", "baseline"}:
                candidates.append({"encoding": "baseline", "scheme": f"baseline__{name}", "bound_scheme": name})
        else:
            raise ValueError(f"未知 cindex 方案: {scheme}")
        for job in candidates:
            key = (job["encoding"], job["scheme"])
            if key in seen:
                continue
            seen.add(key)
            jobs.append(job)
    return jobs


def scheme_output_dir(dataset_name: str, scheme: str, baseline_out: str) -> Path:
    name = bound_scheme_name(scheme)
    if scheme.startswith("baseline__") or name in DEFAULT_BASELINE_SCHEMES:
        root = Path(dataset_baseline_embedding_dir(dataset_name, baseline_out))
        if name in DEFAULT_BASELINE_SCHEMES:
            return root / name / "embeddings" / "pt"
        return root / "baseline" / name / "embeddings" / "pt"
    return Path(dataset_embedding_dir(dataset_name)) / name / "embeddings" / "pt"


def result_table_dir(dataset_name: str, results_root: Path | str | None = None) -> Path:
    root = Path(results_root) if results_root else DEFAULT_RESULTS_ROOT
    return root / DEFAULT_EXP_GROUP / dataset_name


def analyzer_results_base(results_root: Path | str | None = None) -> Path:
    root = Path(results_root) if results_root else DEFAULT_RESULTS_ROOT
    return root


def analyzer_exp_group() -> str:
    return ANALYZER_EXP_GROUP


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


CINDEX_CSV_FIELDS = [
    "dataset",
    "scheme",
    "encoding",
    "modality",
    "clinic_dir",
    "results_dir",
    "log_path",
    "skipped",
    "val_c_index_mean",
    "val_c_index_std",
    "test_c_index_mean",
    "test_c_index_std",
    "source",
]


def _row_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("scheme") or ""),
        str(row.get("encoding") or ""),
        str(row.get("modality") or ""),
    )


def _load_json(path: Path):
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_csv_rows(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [{key: row.get(key, "") for key in CINDEX_CSV_FIELDS} for row in csv.DictReader(f)]


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CINDEX_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in CINDEX_CSV_FIELDS})


def _merge_cindex_rows(existing: list[dict], incoming: list[dict]) -> tuple[list[dict], list[dict]]:
    merged = list(existing or [])
    seen = {_row_key(row) for row in merged}
    added = []
    for row in incoming:
        key = _row_key(row)
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
        added.append(row)
    return merged, added


def _merge_run_config(existing: dict | None, incoming: dict, rows: list[dict]) -> dict:
    config = dict(existing or {})
    config.update(incoming)
    config["rows"] = rows
    config["schemes"] = sorted({str(row.get("scheme") or "") for row in rows if row.get("scheme")})
    config["modalities"] = sorted({str(row.get("modality") or "") for row in rows if row.get("modality")})
    encodings = sorted({str(row.get("encoding") or "") for row in rows if row.get("encoding")})
    config["encoding"] = encodings[0] if len(encodings) == 1 else ",".join(encodings)
    config["modality"] = ",".join(config["modalities"])
    config["log_paths"] = [row.get("log_path") for row in rows]
    return config


def _bash_quote(value: str) -> str:
    return "'" + str(value).replace("'", '\'"\'"\'') + "'"


def conf_filename(study: str, scheme: str, modality: str) -> str:
    return f"{study}__{scheme}__{modality}.conf"


def conf_text(
    *,
    study: str,
    scheme: str,
    modality: str,
    clinic_dir: Path | str,
    split_dir: Path | str,
    results_base: Path | str,
    seed: int = 0,
    max_epochs: int | None = None,
) -> str:
    lines = [
        f"EXP_GROUP={_bash_quote(ANALYZER_EXP_GROUP)}",
        f"RUN_NAME={_bash_quote(f'{study}__{scheme}')}",
        f"PRESET={_bash_quote(modality)}",
        f"STUDY={_bash_quote(study)}",
        f"CLINIC_DIR_PATH={_bash_quote(str(Path(clinic_dir)))}",
        f"SPLIT_DIR_PATH={_bash_quote(str(Path(split_dir)))}",
        f"RESULTS_BASE={_bash_quote(str(Path(results_base)))}",
        "WANDB_MODE=disabled",
        f"SEED={int(seed)}",
    ]
    if max_epochs is not None:
        lines.append(f"MAX_EPOCHS={int(max_epochs)}")
    return "\n".join(lines) + "\n"


def ensure_queue_dirs(root: Path | str | None = None) -> Path:
    root = Path(root) if root else DEFAULT_QUEUE_ROOT
    for name in QUEUE_BUCKETS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def existing_conf_path(root: Path, name: str, buckets: tuple[str, ...] = ("queue", "running", "done")) -> Path | None:
    for bucket in buckets:
        path = root / bucket / name
        if path.exists():
            return path
    return None


def _write_exclusive(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    return True


def _claim_path(src: Path, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return False
    try:
        os.link(src, dest)
    except FileExistsError:
        return False
    except FileNotFoundError:
        return False
    except OSError:
        return False
    try:
        os.unlink(src)
    except FileNotFoundError:
        pass
    return dest.exists() and not src.exists()


def _move_conf(path: Path, bucket: str) -> Path:
    path = Path(path)
    dest = path.parent.parent / bucket / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.resolve() != dest.resolve():
        os.replace(path, dest)
    return dest


def claim_conf(root: Path) -> Path | None:
    root = ensure_queue_dirs(root)
    queue_dir = root / "queue"
    running_dir = root / "running"
    for src in sorted(queue_dir.glob("*.conf")):
        dest = running_dir / src.name
        if dest.exists():
            src.unlink(missing_ok=True)
            continue
        if _claim_path(src, dest):
            return dest
    return None


def mark_done(path: Path) -> Path:
    return _move_conf(path, "done")


def mark_failed(path: Path, error: str | None = None) -> Path:
    dest = _move_conf(path, "failed")
    if error:
        dest.with_suffix(".err").write_text(str(error).rstrip() + "\n", encoding="utf-8")
    return dest


def existing_result_dir(out_dir: Path) -> Path | None:
    if list(out_dir.glob("test_result*.csv")) or list(out_dir.glob("val_result_fold*.csv")):
        return out_dir
    return None


def parse_conf(path: Path) -> dict[str, str]:
    payload = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        payload[key.strip()] = value.strip().strip("'").strip('"')
    return payload


def _split_dir_for(dataset_name: str) -> Path:
    return DEFAULT_ANALYZER_SPLIT_ROOT / display_to_study(dataset_name)


def iter_cindex_jobs(
    *,
    dataset_name: str,
    schemes: list[str],
    datasets: dict,
    baseline_out: str,
    encoding: str = "all",
    modalities: list[str] | tuple[str, ...] | str = DEFAULT_ANALYZER_MODALITY,
    results_root: Path | str | None = None,
    seed: int = 0,
    max_epochs: int | None = None,
) -> list[dict]:
    if not dataset_name:
        raise ValueError("cindex 需要 --dataset，不能走单 JSON 模式")
    bound_schemes = schemes_for_dataset(
        [bound_scheme_name(scheme) for scheme in schemes],
        dataset_name,
        datasets,
    )
    skipped = [scheme for scheme in schemes if bound_scheme_name(scheme) not in bound_schemes]
    if skipped:
        print(f"  skip unbound schemes: {skipped}")
    jobs = expand_cindex_jobs(bound_schemes, encoding)
    if isinstance(modalities, str):
        modality_list = parse_modalities(modalities)
    else:
        modality_list = list(modalities)
    study = display_to_study(dataset_name)
    split_dir = _split_dir_for(dataset_name)
    results_base = analyzer_results_base(results_root)
    out = []
    for job in jobs:
        clinic_dir = scheme_output_dir(dataset_name, job["scheme"], baseline_out)
        if not clinic_dir.is_dir():
            print(f"  skip missing embeddings: {job['scheme']} -> {clinic_dir}")
            continue
        for modality in modality_list:
            if modality in MULTIMODAL_MODALITIES and study not in MULTIMODAL_STUDIES:
                print(f"  skip {modality} for {dataset_name}: multimodal models are {MULTIMODAL_DISPLAY} only")
                continue
            run_name = f"{study}__{job['scheme']}"
            out.append(
                {
                    "dataset": dataset_name,
                    "study": study,
                    "scheme": job["scheme"],
                    "bound_scheme": job["bound_scheme"],
                    "encoding": job["encoding"],
                    "modality": modality,
                    "clinic_dir": clinic_dir,
                    "split_dir": split_dir,
                    "results_base": results_base,
                    "run_name": run_name,
                    "conf_name": conf_filename(study, job["scheme"], modality),
                    "seed": int(seed),
                    "max_epochs": max_epochs,
                    "out_dir": results_dir(
                        DEFAULT_ANALYZER_DIR,
                        ANALYZER_EXP_GROUP,
                        run_name,
                        modality,
                        results_dir_base=results_base,
                    ),
                }
            )
    return out


def enqueue_cindex_jobs(
    jobs: list[dict],
    *,
    queue_root: Path | str | None = None,
) -> dict:
    root = ensure_queue_dirs(queue_root)
    created = []
    existing = []
    retried = []
    for job in jobs:
        name = job["conf_name"]
        found = existing_conf_path(root, name)
        if found is not None:
            existing.append(found)
            continue
        content = conf_text(
            study=job["study"],
            scheme=job["scheme"],
            modality=job["modality"],
            clinic_dir=job["clinic_dir"],
            split_dir=job["split_dir"],
            results_base=job["results_base"],
            seed=job.get("seed", 0),
            max_epochs=job.get("max_epochs"),
        )
        failed = root / "failed" / name
        dest = root / "queue" / name
        if failed.exists():
            dest.write_text(content, encoding="utf-8")
            failed.unlink()
            err = failed.with_suffix(".err")
            err.unlink(missing_ok=True)
            retried.append(dest)
            created.append(dest)
            continue
        if _write_exclusive(dest, content):
            created.append(dest)
        else:
            found = existing_conf_path(root, name)
            if found is not None:
                existing.append(found)
    return {"root": root, "created": created, "existing": existing, "retried": retried}


def run_claimed_conf(
    claimed: Path,
    *,
    analyzer_dir: Path | str | None = None,
    reuse: bool = True,
) -> Path:
    claimed = Path(claimed)
    payload = parse_conf(claimed)
    run_name = payload["RUN_NAME"]
    modality = payload["PRESET"]
    results_base = Path(payload.get("RESULTS_BASE") or DEFAULT_RESULTS_ROOT)
    out_dir = results_dir(
        DEFAULT_ANALYZER_DIR,
        payload.get("EXP_GROUP", ANALYZER_EXP_GROUP),
        run_name,
        modality,
        results_dir_base=results_base,
    )
    if reuse and existing_result_dir(out_dir) is not None:
        print(f"[cindex] reuse existing results: {out_dir}")
        return mark_done(claimed)
    analyzer_dir = Path(analyzer_dir or DEFAULT_ANALYZER_DIR)
    proc = subprocess.run(
        ["bash", str(analyzer_dir / "run.sh"), str(claimed)],
        cwd=str(analyzer_dir),
        check=False,
    )
    if proc.returncode != 0:
        dest = mark_failed(claimed, error=f"run.sh exited {proc.returncode}")
        raise RuntimeError(
            f"Clinic_Analyzer failed for {claimed.name} (exit {proc.returncode}). See {dest} and {out_dir / 'run.log'}"
        )
    return mark_done(claimed)


def wait_for_idle(root: Path, *, poll_seconds: float = 10.0) -> None:
    root = Path(root)
    while True:
        queued = list((root / "queue").glob("*.conf"))
        running = list((root / "running").glob("*.conf"))
        if not queued and not running:
            return
        if queued:
            return
        print(f"[cindex] queue empty, but {len(running)} task(s) still running; waiting...")
        time.sleep(poll_seconds)


def drain_queue(
    root: Path,
    *,
    reuse: bool = True,
    poll_seconds: float = 10.0,
    workers: int = 1,
) -> None:
    workers = max(1, int(workers))

    def _one_worker(worker_id: int | None = None) -> None:
        prefix = f"[cindex] worker={worker_id} " if worker_id is not None else "[cindex] "
        while True:
            claimed = claim_conf(root)
            if claimed is None:
                wait_for_idle(root, poll_seconds=poll_seconds)
                if not list((root / "queue").glob("*.conf")):
                    return
                continue
            gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "")
            print(f"{prefix}claim {claimed.name} gpu={gpu}")
            try:
                dest = run_claimed_conf(claimed, reuse=reuse)
                print(f"{prefix}done {dest.name}")
            except Exception as exc:
                print(f"{prefix}fail {claimed.name}: {exc}")

    if workers == 1:
        _one_worker()
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one_worker, idx) for idx in range(workers)]
        for future in as_completed(futures):
            future.result()


def summarize_dataset(
    *,
    dataset_name: str,
    jobs: list[dict],
    results_root: Path | str | None = None,
    encoding: str,
    modality: str,
) -> list[dict]:
    rows = []
    for job in jobs:
        out_dir = Path(job["out_dir"])
        reuse_dir = existing_result_dir(out_dir)
        if reuse_dir is None:
            print(f"  skip missing results: {job['scheme']} {job['modality']} -> {out_dir}")
            continue
        payload = read_cindex(reuse_dir)
        row = {
            "dataset": dataset_name,
            "scheme": job["scheme"],
            "encoding": job["encoding"],
            "modality": job["modality"],
            "clinic_dir": str(job["clinic_dir"]),
            "results_dir": payload.get("results_dir") or str(out_dir),
            "log_path": str(out_dir / "run.log"),
            "skipped": True,
            "val_c_index_mean": payload.get("val_c_index_mean"),
            "val_c_index_std": payload.get("val_c_index_std"),
            "test_c_index_mean": payload.get("test_c_index_mean"),
            "test_c_index_std": payload.get("test_c_index_std"),
            "source": payload.get("source"),
            "per_fold": payload.get("per_fold"),
            "val_per_fold": payload.get("val_per_fold"),
            "test_per_fold": payload.get("test_per_fold"),
        }
        rows.append(row)
        print(
            "  {}: val={} test={} modality={} log={}".format(
                job["scheme"],
                row["val_c_index_mean"],
                row["test_c_index_mean"],
                job["modality"],
                row["log_path"],
            )
        )
    out_dir = result_table_dir(dataset_name, results_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    existing_config = _load_json(out_dir / "run_config.json") or {}
    existing_rows = list(existing_config.get("rows") or [])
    if not existing_rows:
        existing_rows = _load_csv_rows(out_dir / "cindex.csv")
    merged_rows, added_rows = _merge_cindex_rows(existing_rows, rows)
    skipped = len(rows) - len(added_rows)
    if skipped:
        print(f"[cindex] keep {skipped} existing table row(s), add {len(added_rows)}")
    incoming = {
        "dataset": dataset_name,
        "encoding": encoding,
        "modality": modality,
        "results_dir": str(out_dir),
    }
    _write_csv(out_dir / "cindex.csv", merged_rows)
    _write_json(
        out_dir / "run_config.json",
        _merge_run_config(_load_json(out_dir / "run_config.json"), incoming, merged_rows),
    )
    return merged_rows


def evaluate_dataset_schemes(
    *,
    dataset_name: str,
    schemes: list[str],
    datasets: dict,
    baseline_out: str,
    encoding: str = "all",
    modality: str = DEFAULT_ANALYZER_MODALITY,
    results_root: Path | str | None = None,
    reuse: bool = True,
    max_epochs: int | None = None,
    seed: int = 0,
    extra_args: list[str] | None = None,
    queue_root: Path | str | None = None,
    run_queue: bool = True,
    poll_seconds: float = 10.0,
    workers: int = 1,
) -> list[dict]:
    del extra_args
    jobs = iter_cindex_jobs(
        dataset_name=dataset_name,
        schemes=schemes,
        datasets=datasets,
        baseline_out=baseline_out,
        encoding=encoding,
        modalities=modality,
        results_root=results_root,
        seed=seed,
        max_epochs=max_epochs,
    )
    queued = enqueue_cindex_jobs(jobs, queue_root=queue_root)
    root = queued["root"]
    print(f"[cindex] queue={root} created={len(queued['created'])} existing={len(queued['existing'])} retried={len(queued.get('retried', []))}")
    if run_queue:
        gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "")
        print(f"[cindex] workers={max(1, int(workers))} gpu={gpu}")
        drain_queue(root, reuse=reuse, poll_seconds=poll_seconds, workers=workers)
    return summarize_dataset(
        dataset_name=dataset_name,
        jobs=jobs,
        results_root=results_root,
        encoding=encoding,
        modality=modality,
    )


def run_cindex_queue(
    *,
    jobs: list[dict],
    baseline_out: str,
    encoding: str = "all",
    modality: str = DEFAULT_ANALYZER_MODALITY,
    results_root: Path | str | None = None,
    reuse: bool = True,
    max_epochs: int | None = None,
    seed: int = 0,
    queue_root: Path | str | None = None,
    poll_seconds: float = 10.0,
    workers: int = 1,
) -> dict[str, list[dict]]:
    jobs_by_dataset = {}
    all_jobs = []
    for job in jobs:
        dataset_name = job["name"]
        source = job.get("source") or "lizhe"
        print(f"\n######## Dataset: {dataset_name} [{source}] ########")
        eval_jobs = iter_cindex_jobs(
            dataset_name=dataset_name,
            schemes=list(job.get("schemes") or []),
            datasets=job.get("datasets") or {},
            baseline_out=baseline_out,
            encoding=encoding,
            modalities=modality,
            results_root=results_root,
            seed=seed,
            max_epochs=max_epochs,
        )
        key = f"{dataset_name}[{source}]"
        jobs_by_dataset[key] = eval_jobs
        all_jobs.extend(eval_jobs)
    queued = enqueue_cindex_jobs(all_jobs, queue_root=queue_root)
    root = queued["root"]
    print(f"[cindex] queue={root} created={len(queued['created'])} existing={len(queued['existing'])} retried={len(queued.get('retried', []))}")
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    print(f"[cindex] workers={max(1, int(workers))} gpu={gpu}")
    drain_queue(root, reuse=reuse, poll_seconds=poll_seconds, workers=workers)
    summaries = {}
    for dataset_name, jobs in jobs_by_dataset.items():
        summaries[dataset_name] = summarize_dataset(
            dataset_name=dataset_name,
            jobs=jobs,
            results_root=results_root,
            encoding=encoding,
            modality=modality,
        )
    return summaries
