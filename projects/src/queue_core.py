"""共享队列原语:四桶 → 原子认领 → 状态迁移(2026-10-13 三合一)。

univariate / cindex / search 三个后端共用本模块的机制层;conf 命名模式与
job_key 哈希材料由各调用方传入(保持各自 argv 语义),机制只写一份:

  * ensure_dirs        四桶建目录
  * dump_job/load_job  O_EXCL 写 / 读 conf(JSON)
  * claim              按文件名模式原子认领 queue/ → running/(os.rename),
                       并在 conf 上盖章 claimed_at / claimed_pid / cuda_visible_devices
                       (claimed_pid 是死进程回收的依据,三后端统一有)
  * move / mark_done / mark_failed / release  状态迁移(os.replace)
  * count              按模式数桶
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

BUCKETS = ("queue", "running", "done", "failed")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def json_dumps(payload: dict) -> str:
    def _default(obj):
        if isinstance(obj, Path):
            return str(obj)
        raise TypeError(f"not json serializable: {type(obj)}")

    return json.dumps(payload, ensure_ascii=False, indent=2, default=_default) + "\n"


def job_key_from_payload(payload: dict, skip_keys: set[str]) -> str:
    """job_key = 排除 skip 键后的 payload 排序 JSON 的 sha1 前 12 位。

    skip 键(workers/device/queue_root 等本地参数)不进哈希,保证同一实验
    配置在任何机器/并发数下同键;dataset/landmark 也不进(它们在文件名里)。
    """
    material = {key: payload[key] for key in sorted(payload) if key not in skip_keys}
    blob = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def ensure_dirs(root: Path) -> Path:
    root = Path(root)
    for name in BUCKETS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def dump_job(path: Path, payload: dict) -> bool:
    """O_EXCL 写 conf;已存在返回 False(幂等 enqueue 的基础)。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json_dumps(payload))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return True


def load_job(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def existing_job(root: Path, name: str) -> Path | None:
    for bucket in BUCKETS:
        candidate = Path(root) / bucket / name
        if candidate.exists():
            return candidate
    return None


def claim(root: Path, pattern: str) -> Path | None:
    """按文件名模式从 queue/ 原子认领一个 conf 到 running/。

    pattern 例:"981369e69510__"(univariate job_key 前缀)、"t2b__"(cindex 家族)。
    认领后盖章 claimed_at / claimed_pid / cuda_visible_devices。
    """
    root = ensure_dirs(root)
    queue_dir = root / "queue"
    running_dir = root / "running"
    for src in sorted(queue_dir.glob(f"{pattern}*.conf")):
        dest = running_dir / src.name
        if dest.exists():
            src.unlink(missing_ok=True)
            continue
        try:
            os.rename(src, dest)
        except OSError:
            continue
        try:
            job = load_job(dest)
            job["claimed_at"] = now_utc()
            job["claimed_pid"] = os.getpid()
            job["cuda_visible_devices"] = os.environ.get("CUDA_VISIBLE_DEVICES", "")
            dest.write_text(json_dumps(job), encoding="utf-8")
        except (json.JSONDecodeError, OSError):
            # 非 JSON conf(cindex 的 bash 风格文本)保持原样,只认领不盖章
            pass
        return dest
    return None


def move(path: Path, bucket: str) -> Path:
    path = Path(path)
    dest = path.parent.parent / bucket / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.resolve() != dest.resolve():
        os.replace(path, dest)
    return dest


def mark_done(path: Path) -> Path:
    return move(path, "done")


def mark_failed(path: Path, error: str | None = None) -> Path:
    dest = move(path, "failed")
    if error:
        dest.with_suffix(".err").write_text(str(error).rstrip() + "\n", encoding="utf-8")
    return dest


def release(path: Path) -> Path:
    return move(path, "queue")


def count(root: Path, bucket: str, pattern: str = "*") -> int:
    return len(list((Path(root) / bucket).glob(f"{pattern}*.conf")))
