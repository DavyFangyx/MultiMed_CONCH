"""Config-snapshot queue for E2 subset-selection experiments(机制层 = queue_core)。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from common.paths import config_family_dir
from queue_core import BUCKETS, claim, move, now_utc  # noqa: E402

DEFAULT_ROOT = config_family_dir("Test_3_search")
WORKER_LOCAL_KEYS = {"queue_root", "poll_seconds", "max_jobs", "workers"}


def ensure_dirs(root: Path) -> Path:
    from queue_core import ensure_dirs as _ensure

    return _ensure(root)


def _now() -> str:
    return now_utc()


def _dump(path: Path, payload: dict) -> None:
    from queue_core import json_dumps

    path.write_text(json_dumps(payload), encoding="utf-8")


def _payload(args) -> dict:
    result = {}
    for key, value in vars(args).items():
        if key.startswith("_") or key in WORKER_LOCAL_KEYS:
            continue
        result[key] = str(value) if isinstance(value, Path) else value
    return result


def enqueue(args, datasets: list[str], landmarks: list[str], root: Path | None = None) -> dict:
    root = ensure_dirs(root or getattr(args, "queue_root", None) or DEFAULT_ROOT)
    payload = _payload(args)
    # Dataset/landmark are job dimensions and must not change the shared job key.
    key_payload = dict(payload)
    key_payload.pop("dataset", None)
    key_payload.pop("landmark_time", None)
    key = hashlib.sha1(json.dumps(key_payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    created, existing = [], []
    for dataset in datasets:
        for landmark in landmarks:
            name = f"{key}__{dataset}__landmark_{landmark}.conf"
            found = next(
                (root / bucket / name for bucket in ("queue", "running", "done") if (root / bucket / name).exists()),
                None,
            )
            if found:
                existing.append(found)
                continue
            failed = root / "failed" / name
            if failed.exists():
                job = json.loads(failed.read_text(encoding="utf-8"))
                job["enqueued_at"] = _now()
                for stale_key in ("claimed_at", "claimed_pid", "cuda_visible_devices"):
                    job.pop(stale_key, None)
                target = root / "queue" / name
                _dump(failed, job)
                try:
                    os.rename(failed, target)
                except OSError:
                    existing.append(target if target.exists() else failed)
                else:
                    created.append(target)
                continue
            job = {"job_key": key, "dataset": dataset, "landmark_time": landmark,
                   "args": {**payload, "dataset": dataset, "landmark_time": landmark},
                   "enqueued_at": _now()}
            target = root / "queue" / name
            try:
                fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                existing.append(target)
            except FileExistsError:
                existing.append(target)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(job, ensure_ascii=False, indent=2) + "\n")
            created.append(target)
    return {"root": root, "job_key": key, "created": created, "existing": existing}


def claim(root: Path, job_key: str) -> Path | None:
    """按 job_key 前缀原子认领(机制 = queue_core.claim)。"""
    from queue_core import claim as _claim

    return _claim(root, f"{job_key}__")
