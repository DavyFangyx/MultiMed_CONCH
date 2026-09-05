"""Dataset-level conf queue, modeled on Clinic_Analyzer snapshots.

One conf per (dataset, landmark_time). Multiple GPU workers share the same
queue and claim jobs with an atomic mv, so a running job is not taken again.
Greedy and univariate use separate default roots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from common.paths import PROJECT_ROOT


DEFAULT_QUEUE_ROOT = PROJECT_ROOT / "Clinic_Analyzer" / "configs" / "greedy"
DEFAULT_UNIVARIATE_QUEUE_ROOT = PROJECT_ROOT / "Clinic_Analyzer" / "configs" / "univariate"
BUCKETS = ("queue", "running", "done", "failed")
WORKER_LOCAL_KEYS = ("workers", "device", "conch_python", "analyzer_python", "queue_root")
JOB_KEY_SKIP = set(WORKER_LOCAL_KEYS) | {"dataset", "landmark_tag"}


def queue_root_from_args(args) -> Path:
    raw = getattr(args, "queue_root", None)
    if raw:
        return Path(raw)
    experiment = str(getattr(args, "experiment", "") or "").strip().lower()
    kind = str(getattr(args, "queue_kind", "") or "").strip().lower()
    if kind == "univariate":
        if experiment == "longitudinal":
            return DEFAULT_UNIVARIATE_QUEUE_ROOT.parent / "longitudinal_univariate"
        return DEFAULT_UNIVARIATE_QUEUE_ROOT
    if experiment == "longitudinal":
        return DEFAULT_QUEUE_ROOT.parent / "longitudinal"
    return DEFAULT_QUEUE_ROOT


def ensure_queue_dirs(root: Path) -> Path:
    root = Path(root)
    for name in BUCKETS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _json_default(obj):
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"not json serializable: {type(obj)}")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n"


def args_payload(args) -> dict:
    payload = {}
    for key, value in vars(args).items():
        if key.startswith("_"):
            continue
        if isinstance(value, Path):
            value = str(value)
        payload[key] = value
    if "landmark_time" in payload:
        from common.paths import canonical_landmark_spec

        try:
            payload["landmark_time"] = canonical_landmark_spec(payload["landmark_time"])
        except Exception:
            pass
    return payload


def job_key_from_payload(payload: dict) -> str:
    material = {key: payload[key] for key in sorted(payload) if key not in JOB_KEY_SKIP}
    blob = json.dumps(material, ensure_ascii=False, sort_keys=True, default=_json_default)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def job_key_from_args(args) -> str:
    return job_key_from_payload(args_payload(args))


def job_filename(job_key: str, dataset: str) -> str:
    return f"{job_key}__{dataset}.conf"


def job_stem(dataset: str, landmark_time) -> str:
    from common.paths import landmark_tag

    tag = landmark_tag(landmark_time=landmark_time)
    return f"{dataset}__{tag}"


def job_filename_for(job_key: str, dataset: str, landmark_time) -> str:
    return f"{job_key}__{job_stem(dataset, landmark_time)}.conf"


def dump_job(path: Path, payload: dict) -> bool:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_dumps(payload))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return True


def load_job(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _existing_job_path(root: Path, name: str) -> Path | None:
    for bucket in BUCKETS:
        candidate = root / bucket / name
        if candidate.exists():
            return candidate
    return None


def enqueue_jobs(args, datasets: list[str], *, root: Path | None = None) -> dict:
    root = ensure_queue_dirs(root or queue_root_from_args(args))
    payload = args_payload(args)
    key = job_key_from_payload(payload)
    created = []
    existing = []
    from discovery.landmark import iter_landmark_args

    jobs = []
    for dataset in datasets:
        scan_root = None
        try:
            from common.paths import dataset_field_bank_dir, experiment_from_args, validate_encoding

            encoding = validate_encoding(getattr(args, "encoding", "prompt"))
            experiment = experiment_from_args(args)
            scan_root = dataset_field_bank_dir(dataset, encoding, "landmark_none", experiment=experiment).parent
        except Exception:
            scan_root = None
        for landmark_args in iter_landmark_args(
            args,
            scan_roots=scan_root,
            context=f"queue {dataset}",
        ):
            jobs.append((dataset, landmark_args.landmark_time, landmark_args.landmark_tag))
    multi = len(jobs) > 1 or str(getattr(args, "dataset", "")) == "all" or str(getattr(args, "landmark_time", "")) == "all"
    for dataset, landmark_time, landmark_tag in jobs:
        name = job_filename_for(key, dataset, landmark_time)
        found = _existing_job_path(root, name)
        if found is not None:
            existing.append(found)
            continue
        job = {
            "dataset": dataset,
            "landmark_time": landmark_time,
            "landmark_tag": landmark_tag,
            "job_key": key,
            "multi_dataset": multi,
            "args": dict(payload),
            "enqueued_at": _now(),
        }
        job["args"]["dataset"] = dataset
        job["args"]["landmark_time"] = landmark_time
        job["args"]["landmark_tag"] = landmark_tag
        dest = root / "queue" / name
        if dump_job(dest, job):
            created.append(dest)
        else:
            found = _existing_job_path(root, name)
            if found is not None:
                existing.append(found)
    return {
        "root": root,
        "job_key": key,
        "created": created,
        "existing": existing,
    }


def _claim_path(src: Path, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dest)
    except FileNotFoundError:
        return False
    except FileExistsError:
        return False
    except OSError:
        return False
    return dest.exists() and not src.exists()


def claim_job(root: Path, job_key: str) -> Path | None:
    root = ensure_queue_dirs(root)
    queue_dir = root / "queue"
    running_dir = root / "running"
    for src in sorted(queue_dir.glob(f"{job_key}__*.conf")):
        dest = running_dir / src.name
        if not _claim_path(src, dest):
            continue
        job = load_job(dest)
        job["claimed_at"] = _now()
        job["claimed_pid"] = os.getpid()
        job["cuda_visible_devices"] = os.environ.get("CUDA_VISIBLE_DEVICES", "")
        dest.write_text(_dumps(job), encoding="utf-8")
        return dest
    return None


def _move_job(path: Path, bucket: str) -> Path:
    path = Path(path)
    dest = path.parent.parent / bucket / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.resolve() != dest.resolve():
        os.replace(path, dest)
    return dest


def mark_done(path: Path) -> Path:
    return _move_job(path, "done")


def mark_failed(path: Path, error: str | None = None) -> Path:
    dest = _move_job(path, "failed")
    if error:
        dest.with_suffix(".err").write_text(str(error).rstrip() + "\n", encoding="utf-8")
    return dest


def release_job(path: Path) -> Path:
    return _move_job(path, "queue")


def merge_job_args(worker_args, job: dict):
    merged = argparse.Namespace(**vars(worker_args))
    for key, value in (job.get("args") or {}).items():
        if key in WORKER_LOCAL_KEYS:
            continue
        setattr(merged, key, value)
    merged.dataset = job["dataset"]
    if job.get("landmark_time") is not None:
        merged.landmark_time = job["landmark_time"]
    if job.get("landmark_tag") is not None:
        merged.landmark_tag = job["landmark_tag"]
    merged._multi_dataset = bool(job.get("multi_dataset"))
    return merged


def count_bucket(root: Path, bucket: str, job_key: str | None = None) -> int:
    pattern = f"{job_key}__*.conf" if job_key else "*.conf"
    return len(list((Path(root) / bucket).glob(pattern)))
