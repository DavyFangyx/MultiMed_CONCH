"""Enqueue and drain E2 selection jobs stored as config snapshots."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from common.datasets import load_dataset_configs, resolve_dataset_names
from selection.queue import DEFAULT_ROOT, claim, enqueue, move


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Queue-backed E2 subset selection")
    p.add_argument("--dataset", required=True)
    p.add_argument("--landmark_time", required=True)
    p.add_argument("--algo", required=True)
    p.add_argument("--seed", default="0")
    p.add_argument("--field_bank_dir")
    p.add_argument("--splits")
    p.add_argument("--out")
    p.add_argument("--max_epochs", type=int)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--univariate_csv")
    p.add_argument("--univariate_config")
    p.add_argument("--semantic_embeddings")
    p.add_argument("--conch_ckpt")
    p.add_argument("--conch_python")
    p.add_argument("--semantic_batch_size", type=int, default=64)
    p.add_argument("--anchor_p", type=int)
    p.add_argument("--queue_root", default=str(DEFAULT_ROOT))
    p.add_argument("--poll_seconds", type=float, default=5.0)
    p.add_argument("--max_jobs", type=int, default=0)
    return p


def _landmarks(raw: str) -> list[str]:
    values = [x.strip() for x in raw.split(",") if x.strip()]
    if not values:
        raise ValueError("--landmark_time must not be empty")
    if values == ["all"]:
        return ["0", "365", "730", "none"]
    return values


def _command(job: dict) -> list[str]:
    args = job["args"]
    command = [sys.executable, str(ROOT / "scripts/run_e2_selection.py")]
    for key, value in args.items():
        if value is None:
            continue
        command.extend([f"--{key}", str(value)])
    return command


def _algorithms(raw: str) -> list[str]:
    values = [value.strip() for value in str(raw).split(",") if value.strip()]
    if not values:
        raise ValueError("--algo must not be empty")
    return list(dict.fromkeys(values))


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.workers < 1:
        parser().error("--workers 必须是正整数")
    datasets = resolve_dataset_names(args.dataset, load_dataset_configs(ROOT / "datasets.json"))
    landmarks = _landmarks(args.landmark_time)
    queued = []
    for algorithm in _algorithms(args.algo):
        algorithm_args = copy.copy(args)
        algorithm_args.algo = algorithm
        queued.append(enqueue(algorithm_args, datasets, landmarks))
    root = Path(queued[0]["root"])
    print(json.dumps({"queue_root": str(root),
                      "job_keys": [item["job_key"] for item in queued],
                      "created": sum(len(item["created"]) for item in queued),
                      "existing": sum(len(item["existing"]) for item in queued)}), flush=True)
    processed = 0
    for item in queued:
        while args.max_jobs <= 0 or processed < args.max_jobs:
            path = claim(root, item["job_key"])
            if path is None:
                break
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                print(f"[e2] START {path.name}", flush=True)
                completed = subprocess.run(_command(job), cwd=ROOT, check=False)
                if completed.returncode:
                    raise RuntimeError(f"run_e2_selection.py exited with {completed.returncode}")
            except Exception as exc:
                move(path, "failed")
                (root / "failed" / f"{path.stem}.err").write_text(traceback.format_exc(), encoding="utf-8")
                print(f"[e2] FAIL  {path.name}: {exc}", flush=True)
            else:
                move(path, "done")
                print(f"[e2] OK    {path.name}", flush=True)
            processed += 1
        if args.max_jobs > 0 and processed >= args.max_jobs:
            break
    # A second GPU may still be draining this key. Do not spin forever when this
    # worker sees an empty queue; its jobs are independently claimed atomically.
    print(f"[e2] finished processed={processed}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
