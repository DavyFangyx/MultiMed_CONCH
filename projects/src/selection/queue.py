"""Config-snapshot queue for E2 subset-selection experiments."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


BUCKETS = ("queue", "running", "done", "failed")
DEFAULT_ROOT = Path("Clinic_Analyzer/configs/E2_selection")
WORKER_LOCAL_KEYS = {"queue_root", "poll_seconds", "max_jobs"}


def ensure_dirs(root: Path) -> Path:
    root = Path(root)
    for bucket in BUCKETS:
        (root / bucket).mkdir(parents=True, exist_ok=True)
    return root


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dump(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


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
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(job, ensure_ascii=False, indent=2) + "\n")
            created.append(target)
    return {"root": root, "job_key": key, "created": created, "existing": existing}


def claim(root: Path, job_key: str) -> Path | None:
    root = ensure_dirs(root)
    for source in sorted((root / "queue").glob(f"{job_key}__*.conf")):
        target = root / "running" / source.name
        try:
            os.rename(source, target)
        except OSError:
            continue
        job = json.loads(target.read_text(encoding="utf-8"))
        job.update({"claimed_at": _now(), "claimed_pid": os.getpid(),
                    "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", "")})
        _dump(target, job)
        return target
    return None


def move(path: Path, bucket: str) -> Path:
    target = Path(path).parent.parent / bucket / Path(path).name
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, target)
    return target
