"""S5b / Test_1a off 臂队列助手：enqueue / status / retry / recover / watch / report。

与 drainer（scripts/run_univariate_cindex.py 的 run_claimed_jobs）共享同一 job_key：
本脚本用 univariate_cli.make_parser().parse_args() 以与 drainer 完全相同的 CLI 参数
构造 args，再调用 greedy.queue.enqueue_jobs，保证 payload（及 job_key）逐字一致。

raw 臂参数（与 t0 臂的唯一差异 = 取值 mask 关 + 患者集显式 landmark_0 + 三个根目录改道）：
    --landmark_time none --extraction_mask off --label_tag landmark_0
    --field_bank_root  {ROOT}/outputs/_raw
    --embeddings_root  {ROOT}/outputs/_raw
    --results_dir      {ROOT}/results/Test_1a/arm_off
    --queue_root       {ROOT}/Clinic_Analyzer/configs/Test_1a_off

数据集名单不硬编码：从 datasets.json 注册表取 TCGA- / TCGA_ 前缀（= 33 个 TCGA，spec §2.4）。
运行环境：base python 3.13.12（不训练）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from common.datasets import load_dataset_configs
from common.paths import config_family_dir, test_results_dir
from greedy.queue import (
    count_bucket,
    ensure_queue_dirs,
    enqueue_jobs,
    load_job,
)
from greedy.univariate_cli import make_parser

QUEUE_ROOT = config_family_dir("Test_1a_off")
PARKED_DIR = QUEUE_ROOT / "parked"
RETRY_STATE = QUEUE_ROOT / "retry_state.json"
MAX_RETRIES = 3
RAW_LANDMARK_TAG = "landmark_none"
RAW_BANK_ROOT = ROOT / "outputs" / "_raw"
RAW_RESULTS_ROOT = test_results_dir("Test_1a/arm_off")
RESULTS_ROOT = RAW_RESULTS_ROOT / "univariate" / "prompt" / RAW_LANDMARK_TAG
MANIFEST_PATH = ROOT / "results" / "Test_0_dataset_availability" / "manifest.csv"
EVENT_SUMMARY_PATH = ROOT / "rawdata_stats" / "_shared" / "event_summary.csv"
MIN_EVENT = 100  # R13：Test_1a off 臂训练范围 = n_event >= 100 的 TCGA 主集
PID_DIR = Path(os.environ.get("S5B_PID_DIR", "/tmp/s5b_univariate"))
DRAIN_LOG = Path(os.environ.get("S5B_DRAIN_LOG", "/tmp/s5b_drain.log"))
WATCH_LOG = Path(os.environ.get("S5B_WATCH_LOG", "/tmp/s5b_watch.log"))


def _n_event_from_manifest() -> dict[str, int]:
    import csv

    rows = list(csv.DictReader(open(MANIFEST_PATH, encoding="utf-8")))
    return {
        str(r["dataset"]).strip(): int(str(r["n_event"]).strip())
        for r in rows
        if str(r.get("dataset") or "").strip()
    }


def _n_event_from_event_summary() -> dict[str, int]:
    import csv

    rows = list(csv.DictReader(open(EVENT_SUMMARY_PATH, encoding="utf-8")))
    out = {}
    for r in rows:
        name = str(r.get("dataset") or r.get("dataset_name") or "").strip()
        value = str(r.get("n_event") or "").strip()
        if name and value:
            out[name] = int(float(value))
    return out


def n_event_table() -> dict[str, int]:
    """n_event 表：优先 Test_0 manifest，回退 rawdata_stats/_shared/event_summary.csv（R13 指定的两个来源）。"""
    if MANIFEST_PATH.exists():
        table = _n_event_from_manifest()
        if table:
            return table
    if EVENT_SUMMARY_PATH.exists():
        table = _n_event_from_event_summary()
        if table:
            return table
    raise FileNotFoundError(
        f"未找到 n_event 来源：{MANIFEST_PATH} 或 {EVENT_SUMMARY_PATH}（R13 名单的权威来源）"
    )


def main_datasets() -> list[str]:
    """Test_1a off 臂训练名单（R13）：n_event >= 100 的 TCGA 数据集；不硬编码。"""
    table = n_event_table()
    return sorted(
        name
        for name, n_event in table.items()
        if name.startswith(("TCGA-", "TCGA_")) and int(n_event) >= MIN_EVENT
    )


def all_tcga_datasets() -> list[str]:
    datasets = load_dataset_configs(ROOT / "datasets.json")
    return sorted(name for name in datasets if name.startswith(("TCGA-", "TCGA_")))


def tcga_datasets() -> list[str]:
    """训练/统计口径 = R13 主集。"""
    return main_datasets()


def drainer_argv(datasets: list[str], *, workers: int = 8) -> list[str]:
    return [
        "--dataset", ",".join(datasets),
        "--landmark_time", "none",
        "--extraction_mask", "off",
        "--label_tag", "landmark_0",
        "--field_bank_root", str(RAW_BANK_ROOT),
        "--embeddings_root", str(RAW_BANK_ROOT),
        "--results_dir", str(RAW_RESULTS_ROOT),
        "--queue_root", str(QUEUE_ROOT),
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


def field_csv_path(dataset: str) -> Path:
    return RESULTS_ROOT / dataset / "mlp_clinic_flatten" / "field_cindex.csv"


def _log(msg: str) -> None:
    stamp = datetime.now().strftime("%F_%T")
    line = f"[s5b][{stamp}] {msg}"
    print(line)
    try:
        WATCH_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(WATCH_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def cmd_enqueue(workers: int) -> None:
    datasets = tcga_datasets()
    args = build_args(drainer_argv(datasets, workers=workers))
    result = enqueue_jobs(args, datasets)
    print(
        f"[s5b] enqueue root={result['root']} key={result['job_key']} "
        f"created={len(result['created'])} existing={len(result['existing'])}"
    )


def bucket_counts(job_key: str) -> dict[str, int]:
    return {b: count_bucket(QUEUE_ROOT, b, job_key) for b in ("queue", "running", "done", "failed")}


def cmd_status(workers: int) -> None:
    datasets = tcga_datasets()
    args = build_args(drainer_argv(datasets, workers=workers))
    key = enqueue_jobs(args, datasets)["job_key"]
    counts = bucket_counts(key)
    total = sum(counts.values())
    print(f"[s5b] status key={key} queue={counts['queue']} running={counts['running']} "
          f"done={counts['done']} failed={counts['failed']} total={total}/{len(datasets)}")
    n_csv = 0
    n_complete = 0
    n_rows = 0
    n_err = 0
    for ds in datasets:
        csv_path = field_csv_path(ds)
        if not csv_path.exists():
            continue
        n_csv += 1
        rows = csv_path.read_text(encoding="utf-8").splitlines()
        n = max(0, len(rows) - 1)
        err = sum(1 for line in rows[1:] if ",error," in line)
        n_rows += n
        n_err += err
        print(f"[s5b]   {ds}: rows={n} error={err}")
        if err == 0 and n > 0:
            n_complete += 1
    print(f"[s5b] field_cindex.csv present: {n_csv}/{len(datasets)} "
          f"(error-free: {n_complete}) rows={n_rows} error={n_err}")


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
            continue
        dest = QUEUE_ROOT / "queue" / name
        if dest.exists():
            path.unlink(missing_ok=True)
            continue
        path.rename(dest)
        path.with_suffix(".err").unlink(missing_ok=True)
        state[name] = tries + 1
        moved += 1
        print(f"[s5b] retry requeue {name} (try {tries + 1}/{MAX_RETRIES})")
    RETRY_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if moved or skipped:
        print(f"[s5b] retry moved={moved} skipped={skipped}")


def cmd_recover() -> None:
    """把 running/ 桶里 claimed_pid 已死的 conf 放回 queue/（防 drainer 被杀后任务丢失）。"""
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
    if recovered:
        print(f"[s5b] recover running->queue: {recovered}")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _dataset_from_conf(path: Path) -> str:
    try:
        return str(load_job(path).get("dataset") or "")
    except Exception:
        parts = path.stem.split("__")
        return parts[1] if len(parts) > 1 else ""


def cmd_trim() -> None:
    """R13：把非主集（n_event < 100）任务从 queue/running/failed 撤下，移到 parked/（不删除，可回滚）。"""
    ensure_queue_dirs(QUEUE_ROOT)
    main = set(main_datasets())
    PARKED_DIR.mkdir(parents=True, exist_ok=True)
    moved = 0
    for bucket in ("queue", "running", "failed"):
        for path in sorted((QUEUE_ROOT / bucket).glob("*.conf")):
            dataset = _dataset_from_conf(path)
            if dataset in main:
                continue
            dest = PARKED_DIR / path.name
            if dest.exists():
                path.unlink(missing_ok=True)
            else:
                path.rename(dest)
            path.with_suffix(".err").unlink(missing_ok=True)
            moved += 1
            print(f"[s5b] trim {bucket}/{path.name} -> parked/")
    print(f"[s5b] trim moved={moved} (main set={len(main)})")


def _start_drainer(gpu: str, workers: int, python_exe: str) -> int:
    PID_DIR.mkdir(parents=True, exist_ok=True)
    DRAIN_LOG.parent.mkdir(parents=True, exist_ok=True)
    datasets = tcga_datasets()
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    env["OMP_NUM_THREADS"] = env.get("OMP_NUM_THREADS", "2")
    env["OPENBLAS_NUM_THREADS"] = env.get("OPENBLAS_NUM_THREADS", "1")
    env["MKL_NUM_THREADS"] = env.get("MKL_NUM_THREADS", "1")
    with open(DRAIN_LOG, "ab") as log:
        proc = subprocess.Popen(
            [python_exe, str(ROOT / "scripts" / "run_univariate_cindex.py"), *drainer_argv(datasets, workers=workers)],
            cwd=str(ROOT),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    (PID_DIR / f"gpu{gpu}.pid").write_text(f"{proc.pid}\n", encoding="utf-8")
    return proc.pid


def _drainer_alive(gpu: str) -> bool:
    pidfile = PID_DIR / f"gpu{gpu}.pid"
    if not pidfile.exists():
        return False
    try:
        return _pid_alive(int(pidfile.read_text().strip()))
    except Exception:
        return False


def cmd_drain(gpus: list[str], workers: int, python_exe: str) -> None:
    for gpu in gpus:
        pid = _start_drainer(gpu, workers, python_exe)
        print(f"[s5b] drainer GPU {gpu} PID {pid}")


def cmd_watch(gpus: list[str], workers: int, python_exe: str, interval: int = 60) -> None:
    """自愈循环：recover + retry + 重启死掉的 drainer；全部 done 后 report 并退出。"""
    datasets = tcga_datasets()
    expected = len(datasets)
    args = build_args(drainer_argv(datasets, workers=workers))
    key = enqueue_jobs(args, datasets)["job_key"]
    _log(f"watch start key={key} expected={expected} gpus={','.join(gpus)} workers={workers}")
    last_status = 0.0
    while True:
        cmd_recover()
        cmd_retry()
        counts = bucket_counts(key)
        if counts["queue"] > 0:
            for gpu in gpus:
                if not _drainer_alive(gpu):
                    pid = _start_drainer(gpu, workers, python_exe)
                    _log(f"relaunch drainer GPU {gpu} PID {pid} (queue={counts['queue']} running={counts['running']})")
        now = time.time()
        if now - last_status >= 300:
            _log(
                f"status queue={counts['queue']} running={counts['running']} "
                f"done={counts['done']} failed={counts['failed']}"
            )
            last_status = now
        if counts["done"] >= expected and counts["queue"] == 0 and counts["running"] == 0:
            _log(f"ALL {expected} done")
            cmd_report()
            _log("watch exit")
            return
        time.sleep(interval)


def cmd_report() -> None:
    datasets = tcga_datasets()
    total_rows = 0
    total_ok = 0
    total_err = 0
    missing = []
    payload = {}
    for ds in datasets:
        csv_path = field_csv_path(ds)
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
        payload[ds] = {"rows": ok + err, "ok": ok, "error": err}
    print(f"[s5b] report datasets_with_csv={len(datasets) - len(missing)}/{len(datasets)} "
          f"field_rows={total_rows} ok={total_ok} error={total_err}")
    if missing:
        print(f"[s5b] missing: {missing}")
    out = RAW_RESULTS_ROOT / "_s5b_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"n_datasets": len(datasets), "missing": missing, "rows": total_rows,
             "ok": total_ok, "error": total_err, "per_dataset": payload},
            ensure_ascii=False, indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"[s5b] report json: {out}")


def main() -> int:
    parser = argparse.ArgumentParser(description="S5b / Test_1a off 臂 univariate queue helper")
    parser.add_argument("command", choices=["enqueue", "status", "retry", "recover", "drain", "watch", "report", "trim"])
    parser.add_argument("--workers", type=int, default=int(os.environ.get("S5B_WORKERS", "8")))
    parser.add_argument("--gpus", default=os.environ.get("S5B_GPUS", "7"))
    parser.add_argument("--python3", default=os.environ.get("S5B_PYTHON3", "python3"))
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    gpus = [g.strip() for g in str(args.gpus).split(",") if g.strip()]
    if args.command == "enqueue":
        cmd_enqueue(args.workers)
    elif args.command == "status":
        cmd_status(args.workers)
    elif args.command == "retry":
        cmd_retry()
    elif args.command == "recover":
        cmd_recover()
    elif args.command == "drain":
        cmd_drain(gpus, args.workers, args.python3)
    elif args.command == "watch":
        cmd_watch(gpus, args.workers, args.python3, interval=args.interval)
    elif args.command == "report":
        cmd_report()
    elif args.command == "trim":
        cmd_trim()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
