"""Test_3 贪婪搜索队列助手：enqueue / status / recover / retry / drain / watch / report。

搜索定义（spec §7.1 + D4）：A2_greedy × landmark_0 field bank × mlp_clinic_flatten × seed 0
× 5 折；早停 sig_stop（gain < 0.005 且 paired Wilcoxon p >= 0.05 连续 3 步），另报历史 best。

队列机制复用 E2（`src/selection/queue.py`，只读复用，不改 E 组算法）：
  * 每个数据集一个 conf（`--out` 含数据集名，故 job_key 逐数据集独立）；
  * drainer = `scripts/run_e2_selection_queue.py`（enqueue 幂等 + claim + 训练 + move）；
  * watch 自愈：running 悬挂回收 / failed 限次重试 / drainer 死了拉起 / 全 done 汇总退出。

用法（projects/ 根目录，base python 3.13.12，不训练）：
  python3 scripts/Test_3_search_queue.py enqueue
  python3 scripts/Test_3_search_queue.py status
  python3 scripts/Test_3_search_queue.py recover
  python3 scripts/Test_3_search_queue.py retry
  python3 scripts/Test_3_search_queue.py drain --gpus 1
  python3 scripts/Test_3_search_queue.py watch --gpus 1,0,3 --interval 60
  python3 scripts/Test_3_search_queue.py report
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import Test_3_common as C  # noqa: E402
from selection.queue import DEFAULT_ROOT, enqueue, move  # noqa: E402

QUEUE_ROOT = DEFAULT_ROOT
LOG_ROOT = C.OUT_ROOT / "logs"
MAX_RETRIES = 3
BUCKETS = ("queue", "running", "done", "failed")


def _runner_argv(dataset: str, workers: int | None = None) -> list[str]:
    """drainer 命令行（脚本之后的 argv 亦直接送进 drainer 自己的 parser 求 job args）。"""
    argv = [
        sys.executable, str(ROOT / "scripts" / "run_e2_selection_queue.py"),
        "--dataset", dataset,
        "--landmark_time", str(C.LANDMARK_TIME),
        "--algo", C.ALGO,
        "--seed", str(C.SEED),
        "--out", str(C.search_dir(dataset)),
        "--inner_analyzer", C.ANALYZER,
    ]
    if workers is not None:
        argv.extend(["--workers", str(workers)])
    return argv


def _workers_for(gpu: str) -> int:
    """按 GPU 取 drainer workers：T3_SEARCH_WORKERS_MAP="0:32,2:32,3:32"（gpu:workers 对），
    未列出的 GPU 用 T3_SEARCH_WORKERS（默认 16）。"""
    try:
        mapping = {
            part.split(":")[0]: int(part.split(":")[1])
            for part in os.environ.get("T3_SEARCH_WORKERS_MAP", "").split(",")
            if ":" in part
        }
    except (TypeError, ValueError):
        mapping = {}
    return mapping.get(gpu, int(os.environ.get("T3_SEARCH_WORKERS", "16")))


_RUNNER_MODULE = None


def _runner_module():
    """加载 drainer 模块，借用它的 parser——job_key 哈希全部 argparse 字段，
    手抄默认值极易漂移，故直接复用同一 parser 保证逐位一致。"""
    global _RUNNER_MODULE
    if _RUNNER_MODULE is None:
        path = ROOT / "scripts" / "run_e2_selection_queue.py"
        spec = importlib.util.spec_from_file_location("run_e2_selection_queue", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _RUNNER_MODULE = module
    return _RUNNER_MODULE


def _job_args(dataset: str):
    """与 drainer 完全同源的参数命名空间（enqueue 的 job_key 由它决定）。"""
    return _runner_module().parser().parse_args(_runner_argv(dataset)[2:])


def conf_path(dataset: str, bucket: str = "queue") -> Path:
    """conf 文件名 = {job_key}__{dataset}__landmark_{tag}.conf；job_key 由 enqueue 决定。"""
    matches = sorted((QUEUE_ROOT / bucket).glob(f"*__{dataset}__landmark_{C.LANDMARK_TIME}.conf"))
    return matches[0] if matches else QUEUE_ROOT / bucket / f"{{job_key}}__{dataset}__landmark_{C.LANDMARK_TIME}.conf"


def conf_exists(dataset: str) -> str | None:
    for bucket in BUCKETS:
        if list((QUEUE_ROOT / bucket).glob(f"*__{dataset}__landmark_{C.LANDMARK_TIME}.conf")):
            return bucket
    return None


def cmd_enqueue(datasets: list[str]) -> None:
    created = existing = 0
    for dataset in datasets:
        result = enqueue(_job_args(dataset), [dataset], [str(C.LANDMARK_TIME)], root=QUEUE_ROOT)
        created += len(result["created"])
        existing += len(result["existing"])
    print(f"[test_3][enqueue] created={created} existing={existing} queue_root={QUEUE_ROOT}", flush=True)


def cmd_status(datasets: list[str]) -> None:
    counts = {bucket: 0 for bucket in BUCKETS}
    counts["missing"] = 0
    for dataset in datasets:
        bucket = conf_exists(dataset)
        if bucket is None:
            counts["missing"] += 1
        else:
            counts[bucket] += 1
    print(f"[test_3][status] {counts}", flush=True)
    for dataset in datasets:
        bucket = conf_exists(dataset)
        extra = ""
        path = C.search_result_json(dataset)
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            extra = (f" k={payload.get('recommended_k')} c={payload.get('recommended_cv_c_mean')}"
                     f" best_k={len(payload.get('best_subset') or [])}"
                     f" best_c={payload.get('best_cv_c_mean')}"
                     f" stop={payload.get('stop_reason')} evals={payload.get('logical_evals')}")
        print(f"[test_3][status] {dataset:12s} {bucket or '-':8s}{extra}", flush=True)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def cmd_recover(datasets: list[str]) -> int:
    """running/ 里 claimed_pid 已死的 conf 放回 queue/（drainer 被杀后任务不丢）。"""
    recovered = 0
    for dataset in datasets:
        path = conf_path(dataset, "running")
        if not path.exists():
            continue
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if _pid_alive(int(job.get("claimed_pid") or 0)):
            continue
        for key in ("claimed_at", "claimed_pid", "cuda_visible_devices"):
            job.pop(key, None)
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        move(path, "queue")
        recovered += 1
    if recovered:
        print(f"[test_3][recover] requeued {recovered}", flush=True)
    return recovered


def cmd_retry(datasets: list[str], max_retries: int = MAX_RETRIES) -> int:
    """failed/ 桶限次重入队（conf 内记 retries）。"""
    retried = 0
    for dataset in datasets:
        path = conf_path(dataset, "failed")
        if not path.exists():
            continue
        job = json.loads(path.read_text(encoding="utf-8"))
        attempts = int(job.get("retries") or 0)
        if attempts >= max_retries:
            continue
        job["retries"] = attempts + 1
        for key in ("claimed_at", "claimed_pid", "cuda_visible_devices"):
            job.pop(key, None)
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        move(path, "queue")
        retried += 1
    if retried:
        print(f"[test_3][retry] requeued {retried}", flush=True)
    return retried


def log_path(dataset: str) -> Path:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    return LOG_ROOT / f"search_{dataset}.log"


def _pid_path(dataset: str) -> Path:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    return LOG_ROOT / f"search_{dataset}.pid"


def _start_drainer(dataset: str, gpu: str) -> int:
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    argv = _runner_argv(dataset, workers=_workers_for(gpu))
    with log_path(dataset).open("a", encoding="utf-8") as handle:
        handle.write(f"\n===== start {time.strftime('%F %T')} gpu={gpu}\n")
        handle.write("argv: " + " ".join(argv) + "\n")
        handle.flush()
        proc = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=handle,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    _pid_path(dataset).write_text(f"{proc.pid}\n", encoding="utf-8")
    return proc.pid


def drainer_pid(dataset: str) -> int:
    path = _pid_path(dataset)
    if not path.exists():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip() or 0)
    except ValueError:
        return 0


def _claimed_alive(dataset: str) -> bool:
    """conf 里记录的 claim 进程（drainer）是否还在。"""
    path = conf_path(dataset, "running")
    if not path.exists():
        return False
    try:
        return _pid_alive(int(json.loads(path.read_text(encoding="utf-8")).get("claimed_pid") or 0))
    except Exception:
        return False


def _seed_occupied(datasets: list[str], occupied: dict[str, str]) -> dict[str, str]:
    """watch 重启后从 running/ 桶恢复在跑任务，避免重复拉起同一数据集。"""
    for dataset in datasets:
        if dataset in occupied:
            continue
        path = conf_path(dataset, "running")
        if not path.exists():
            continue
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if _pid_alive(int(job.get("claimed_pid") or 0)):
            occupied[dataset] = str(job.get("cuda_visible_devices") or "").strip() or "__running__"
    return occupied


def _schedule(datasets: list[str], gpus: list[str], occupied: dict[str, str]) -> dict[str, str]:
    """空闲 GPU slot 上拉起待跑数据集的 drainer（gpus 列表可重复条目以表示每卡多槽）。"""
    occupied = _seed_occupied(datasets, occupied)
    for dataset, gpu in list(occupied.items()):
        if conf_exists(dataset) in ("done", "failed"):
            occupied.pop(dataset, None)
            continue
        if _pid_alive(drainer_pid(dataset)) or _claimed_alive(dataset):
            continue
        occupied.pop(dataset, None)
    free = [gpu for gpu in gpus if gpu not in occupied.values()]
    for dataset in datasets:
        if conf_exists(dataset) in ("done", "failed"):
            continue
        if dataset in occupied:
            continue
        if not free:
            break
        gpu = free.pop(0)
        pid = _start_drainer(dataset, gpu)
        occupied[dataset] = gpu
        print(f"[test_3][drain] start {dataset} gpu={gpu} pid={pid} log={log_path(dataset)}", flush=True)
    return occupied


def cmd_drain(datasets: list[str], gpus: list[str]) -> None:
    _schedule(datasets, gpus, {})


def cmd_watch(datasets: list[str], gpus: list[str], interval: int, max_retries: int,
              max_hours: float) -> None:
    """自愈循环：recover + retry + 拉起死掉的 drainer；全 done 后 report 退出。"""
    started = time.time()
    occupied: dict[str, str] = {}
    print(f"[test_3][watch] start datasets={len(datasets)} gpus={','.join(gpus)} interval={interval}s",
          flush=True)
    while True:
        cmd_recover(datasets)
        cmd_retry(datasets, max_retries)
        occupied = _schedule(datasets, gpus, occupied)
        done = sum(1 for dataset in datasets if conf_exists(dataset) == "done")
        failed = [dataset for dataset in datasets if conf_exists(dataset) == "failed"]
        print(f"[test_3][watch] {time.strftime('%F %T')} done={done}/{len(datasets)} "
              f"running={sum(1 for d in datasets if conf_exists(d) == 'running')} "
              f"queue={sum(1 for d in datasets if conf_exists(d) == 'queue')} "
              f"failed={len(failed)}", flush=True)
        if done == len(datasets):
            print("[test_3][watch] ALL done", flush=True)
            cmd_report(datasets)
            print("[test_3][watch] exit", flush=True)
            return
        if not occupied and all(conf_exists(d) in ("done", "failed") for d in datasets):
            print(f"[test_3][watch] nothing left to run (failed={failed}); exit", flush=True)
            cmd_report(datasets)
            return
        if max_hours and (time.time() - started) / 3600.0 >= max_hours:
            print(f"[test_3][watch] reached --max_hours {max_hours}; exit", flush=True)
            return
        time.sleep(max(5, interval))


def cmd_report(datasets: list[str]) -> None:
    rows = []
    for dataset in datasets:
        path = C.search_result_json(dataset)
        if not path.exists():
            rows.append({"dataset": dataset, "status": "missing"})
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload.get("metadata") or {}
        stop_path = meta.get("sig_stop_path") or []
        rows.append({
            "dataset": dataset,
            "status": "ok",
            "stop_reason": payload.get("stop_reason"),
            "recommended_k": payload.get("recommended_k"),
            "recommended_cv_c_mean": payload.get("recommended_cv_c_mean"),
            "best_k": len(payload.get("best_subset") or []),
            "best_cv_c_mean": payload.get("best_cv_c_mean"),
            "logical_evals": payload.get("logical_evals"),
            "physical_trains": payload.get("physical_trains"),
            "cache_hits": payload.get("cache_hits"),
            "failure_count": payload.get("failure_count"),
            "wall_s": round(float(payload.get("wall_ms") or 0) / 1000.0, 1),
            "wilcoxon_fallback": meta.get("wilcoxon_fallback"),
            "recommended_subset": ";".join(payload.get("recommended_subset") or []),
            "best_subset": ";".join(payload.get("best_subset") or []),
        })
    out = C.OUT_ROOT / "search_summary.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[test_3][report] {out} rows={len(rows)}", flush=True)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Test_3 搜索队列助手")
    parser.add_argument("command", choices=["enqueue", "status", "recover", "retry", "drain",
                                            "watch", "report"])
    parser.add_argument("--gpus", default="1",
                        help="训练 GPU，逗号分隔（可重复条目表示每卡多槽）")
    parser.add_argument("--interval", type=int, default=60, help="watch 轮询秒数")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES)
    parser.add_argument("--max-hours", type=float, default=0.0, help="watch 最长运行小时（0=不限）")
    parser.add_argument("--datasets", default=None, help="可选：覆盖数据集名单（冒烟/调试用）")
    return parser


def main(argv=None) -> int:
    args = parse_args(argv).parse_args(argv)
    datasets = ([x.strip() for x in args.datasets.split(",") if x.strip()]
                if args.datasets else C.main_datasets())
    gpus = [x.strip() for x in args.gpus.split(",") if x.strip()]
    if args.command == "enqueue":
        cmd_enqueue(datasets)
    elif args.command == "status":
        cmd_status(datasets)
    elif args.command == "recover":
        cmd_recover(datasets)
    elif args.command == "retry":
        cmd_retry(datasets, args.max_retries)
    elif args.command == "drain":
        cmd_drain(datasets, gpus)
    elif args.command == "watch":
        cmd_watch(datasets, gpus, args.interval, args.max_retries, args.max_hours)
    elif args.command == "report":
        cmd_report(datasets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
