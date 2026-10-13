"""Dataset-level conf queue(univariate/greedy 后端)。

一个 conf 对应一个 (dataset, landmark_time)。多 GPU worker 共享同一队列,
以原子 mv 认领,在跑任务不会被重复取走。**机制层(四桶/认领/状态迁移)统一
在 `src/queue_core.py`**,本文件只保留本后端的 job_key 材料与 enqueue 语义。

Univariate 有默认根;greedy 必须显式传 --queue_root(D0 家族根已删除)。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from common.paths import config_family_dir
from queue_core import (  # noqa: E402  机制层三后端合一(2026-10-13)
    BUCKETS,
    count,
    dump_job,
    ensure_dirs,
    existing_job,
    job_key_from_payload as _core_job_key,
    load_job,
    mark_done,
    mark_failed,
    release,
)
from queue_core import now_utc as _now  # noqa: E402

# D0 家族 Clinic_Analyzer/configs/greedy 已删除:greedy 队列根必须显式传 --queue_root。
DEFAULT_QUEUE_ROOT = None
DEFAULT_UNIVARIATE_QUEUE_ROOT = config_family_dir("Test_1a_t0")
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
    # D0 家族 Clinic_Analyzer/configs/greedy 已删除:greedy 队列根必须显式给出。
    raise ValueError(
        "greedy 队列根必须显式传 --queue_root(例如 Clinic_Analyzer/configs/Test_3_search);"
        "D0 家族 Clinic_Analyzer/configs/greedy 已删除,不再提供默认队列根"
    )


def ensure_queue_dirs(root: Path) -> Path:
    return ensure_dirs(root)


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
    return _core_job_key(payload, JOB_KEY_SKIP)


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
            scan_root = dataset_field_bank_dir(dataset, encoding, "no_mask", experiment=experiment).parent
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
        found = existing_job(root, name)
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
            found = existing_job(root, name)
            if found is not None:
                existing.append(found)
    return {
        "root": root,
        "job_key": key,
        "created": created,
        "existing": existing,
    }


def claim_job(root: Path, job_key: str) -> Path | None:
    """按 job_key 前缀原子认领(机制 = queue_core.claim,带 claimed_pid 盖章)。"""
    from queue_core import claim

    return claim(root, f"{job_key}__")


def release_job(path: Path) -> Path:
    return release(path)


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
    pattern = f"{job_key}__" if job_key else "*"
    return count(root, bucket, pattern)
