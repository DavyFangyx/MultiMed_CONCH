"""S5 univariate 补跑队列助手：enqueue / status / retry / recover / report。

与 drainer（scripts/run_univariate_cindex.py 的 run_claimed_jobs）共享同一 job_key：
本脚本用 univariate_cli.make_parser().parse_args() 以与 drainer 完全相同的 CLI 参数
构造 args，再调用 greedy.queue.enqueue_jobs，保证 payload（及 job_key）逐字一致。

数据集名单不硬编码：从 datasets.json 注册表取 TCGA- 前缀（= 33 个 TCGA，spec §2.4）。
运行环境：base python 3.13.12（不训练）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from common.datasets import load_dataset_configs
from greedy.queue import (
    DEFAULT_UNIVARIATE_QUEUE_ROOT,
    count_bucket,
    ensure_queue_dirs,
    enqueue_jobs,
    load_job,
)
from greedy.univariate_cli import make_parser

QUEUE_ROOT = DEFAULT_UNIVARIATE_QUEUE_ROOT
RETRY_STATE = QUEUE_ROOT / "retry_state.json"
MAX_RETRIES = 3
LANDMARK_TAG = "landmark_0"
EXPECTED_JOBS = 33


def tcga_datasets() -> list[str]:
    datasets = load_dataset_configs(ROOT / "datasets.json")
    return sorted(name for name in datasets if name.startswith("TCGA-") or name.startswith("TCGA_"))


def drainer_argv(datasets: list[str], *, workers: int = 8) -> list[str]:
    return [
        "--dataset", ",".join(datasets),
        "--landmark_time", "0",
        "--encoding", "prompt",
        "--analyzer", "mlp_clinic_flatten",
        "--seed", "0",
        "--workers", str(workers),
    ]


def build_args(argv: list[str]) -> argparse.Namespace:
    parser = make_parser()
    args = parser.parse_args(argv)
    args.queue_kind = "univariate"
    return args


def cmd_enqueue(workers: int) -> None:
    datasets = tcga_datasets()
    args = build_args(drainer_argv(datasets, workers=workers))
    result = enqueue_jobs(args, datasets)
    print(
        f"[s5] enqueue root={result['root']} key={result['job_key']} "
        f"created={len(result['created'])} existing={len(result['existing'])}"
    )
    for path in result["created"]:
        print(f"[s5]   + {path.name}")


def bucket_counts(job_key: str) -> dict[str, int]:
    return {b: count_bucket(QUEUE_ROOT, b, job_key) for b in ("queue", "running", "done", "failed")}


def cmd_status(workers: int) -> None:
    datasets = tcga_datasets()
    args = build_args(drainer_argv(datasets, workers=workers))
    key = enqueue_jobs(args, datasets)["job_key"]
    counts = bucket_counts(key)
    total = sum(counts.values())
    print(f"[s5] status key={key} queue={counts['queue']} running={counts['running']} "
          f"done={counts['done']} failed={counts['failed']} total={total}/{EXPECTED_JOBS}")
    results_root = ROOT / "results" / "univariate" / "prompt" / LANDMARK_TAG
    n_csv = 0
    n_complete = 0
    for ds in datasets:
        csv_path = results_root / ds / "mlp_clinic_flatten" / "field_cindex.csv"
        if not csv_path.exists():
            continue
        n_csv += 1
        rows = [line for line in csv_path.read_text(encoding="utf-8").splitlines()]
        n_rows = max(0, len(rows) - 1)
        n_err = sum(1 for line in rows[1:] if ",error," in line)
        print(f"[s5]   {ds}: rows={n_rows} error={n_err}")
        if n_err == 0 and n_rows > 0:
            n_complete += 1
    print(f"[s5] field_cindex.csv present: {n_csv}/{EXPECTED_JOBS} (error-free: {n_complete})")


def cmd_retry() -> None:
    ensure_queue_dirs(QUEUE_ROOT)
    state = {}
    if RETRY_STATE.exists():
        try:
            state = json.loads(RETRY_STATE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    failed = sorted((QUEUE_ROOT / "failed").glob("*.conf"))
    moved = 0
    skipped = 0
    for path in failed:
        name = path.name
        tries = int(state.get(name, 0))
        if tries >= MAX_RETRIES:
            skipped += 1
            print(f"[s5] retry skip (max {MAX_RETRIES}): {name}")
            continue
        dest = QUEUE_ROOT / "queue" / name
        if dest.exists():
            path.unlink(missing_ok=True)
            continue
        path.rename(dest)
        path.with_suffix(".err").unlink(missing_ok=True)
        state[name] = tries + 1
        moved += 1
        print(f"[s5] retry requeue {name} (try {tries + 1}/{MAX_RETRIES})")
    RETRY_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[s5] retry moved={moved} skipped={skipped}")


def cmd_recover() -> None:
    """把 running/ 桶里 claimed_pid 已死的 conf 放回 queue/（防 drainer 被杀后任务丢失）。"""
    import os

    ensure_queue_dirs(QUEUE_ROOT)
    running = sorted((QUEUE_ROOT / "running").glob("*.conf"))
    recovered = 0
    for path in running:
        try:
            job = load_job(path)
        except Exception:
            continue
        pid = job.get("claimed_pid")
        if pid and _pid_alive(int(pid)):
            continue
        dest = QUEUE_ROOT / "queue" / path.name
        if not dest.exists():
            path.rename(dest)
            recovered += 1
    print(f"[s5] recover running->queue: {recovered}")


def _pid_alive(pid: int) -> bool:
    import os

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def cmd_report() -> None:
    results_root = ROOT / "results" / "univariate" / "prompt" / LANDMARK_TAG
    datasets = tcga_datasets()
    total_rows = 0
    total_ok = 0
    total_err = 0
    missing = []
    for ds in datasets:
        csv_path = results_root / ds / "mlp_clinic_flatten" / "field_cindex.csv"
        if not csv_path.exists():
            missing.append(ds)
            continue
        lines = csv_path.read_text(encoding="utf-8").splitlines()
        ok = err = 0
        for line in lines[1:]:
            if ",ok," in line:
                ok += 1
            elif ",error," in line:
                err += 1
        total_rows += ok + err
        total_ok += ok
        total_err += err
    print(f"[s5] report datasets_with_csv={len(datasets) - len(missing)}/{len(datasets)} "
          f"field_rows={total_rows} ok={total_ok} error={total_err}")
    if missing:
        print(f"[s5] missing: {missing}")


def main() -> int:
    parser = argparse.ArgumentParser(description="S5 univariate queue helper")
    parser.add_argument("command", choices=["enqueue", "status", "retry", "recover", "report"])
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.command == "enqueue":
        cmd_enqueue(args.workers)
    elif args.command == "status":
        cmd_status(args.workers)
    elif args.command == "retry":
        cmd_retry()
    elif args.command == "recover":
        cmd_recover()
    elif args.command == "report":
        cmd_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
