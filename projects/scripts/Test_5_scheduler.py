#!/usr/bin/env python3
"""Test_5 多卡调度器：只在 0-3 的空闲卡上起 drainer，每卡一个 drainer，最多 4 并发。

硬性约束（公共服务器）：
  * 只用 GPU 0-3；4-7 绝不碰；同时最多 4 个 drainer（= 4 张卡上限）；
  * 空闲判据 = util < 15% 且显存占用 < FREE_MEM_MAX_MB（默认 1500MiB）；
    放置前对同一张卡再查一次（re-check），不空闲就跳过，等下一轮；
  * 不 kill 任何别人的进程：本调度器只回收自己 spawn 的 drainer（proc.poll()）。
  * 每个子检查至多一个 drainer（避免两个 drainer 抢同一队列的同名 conf——cindex
    claim 是原子的、不会重复跑，但分工会乱）；空闲卡优先分给剩余 conf 最多的子检查。

用法（projects/ 根目录）：
  setsid nohup nice -n 10 python3 scripts/Test_5_scheduler.py --sub 5M_2b --sub 5E_2b \
      --sub 5E_3 --sub 5M_3 >> results/Test_5_invariance/logs/scheduler.out 2>&1 &
  查看：tail -f results/Test_5_invariance/logs/scheduler.log
  停止：kill "$(cat results/Test_5_invariance/logs/scheduler.pid)"
  dry check：python3 scripts/Test_5_scheduler.py --once
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import Test_5_common as C  # noqa: E402

GPU_RANGE = (0, 1, 2, 3)          # 公共服务器约定：只用 0-3
FREE_UTIL_MAX = 15.0              # %
# 空卡实测 14-17MiB；任何一个活着的训练进程 >=500MiB。取 800MiB 以免和"别人正在跑但
# 当前 util 低"的卡共置（例如 results_display 的 Table1 脚本常驻 1.3GB/@0% util）。
FREE_MEM_MAX_MB = 800.0           # MiB
MAX_DRAINERS = 4                  # = 可用卡数上限
DEFAULT_SUB_ORDER = ("5M_2b", "5E_2b", "5E_3", "5M_3")   # 剩余多者优先只作 tie-break 之外的第二判据
LOG_DIR = C.LOG_ROOT
PID_PATH = LOG_DIR / "scheduler.pid"
LOG_PATH = LOG_DIR / "scheduler.log"


def log(msg: str) -> None:
    line = f"{time.strftime('[%F %T]')} {msg}"
    print(line, flush=True)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def gpu_stats() -> dict[int, tuple[float, float]]:
    """{gpu: (util%, mem MiB)}；nvidia-smi 失败返回空 dict（本轮不放置）。"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout
    except Exception as exc:  # noqa: BLE001
        log(f"nvidia-smi failed: {exc}")
        return {}
    stats: dict[int, tuple[float, float]] = {}
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            stats[int(parts[0])] = (float(parts[1]), float(parts[2]))
        except ValueError:
            continue
    return stats


def is_free(stats: dict[int, tuple[float, float]], gpu: int) -> bool:
    util, mem = stats.get(gpu, (1e9, 1e9))
    return util < FREE_UTIL_MAX and mem < FREE_MEM_MAX_MB


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def spawn_drainer(sub: str, gpu: int, workers: int) -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"drain_{sub}_gpu{gpu}.log"
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    argv = ["nice", "-n", "10", sys.executable, "-u",
            str(ROOT / "scripts" / "Test_5_drain.py"),
            "--sub", sub, "--gpu", str(gpu), "--workers", str(workers)]
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n===== scheduler spawn {time.strftime('%F %T')} "
                     f"gpu={gpu} sub={sub} workers={workers}\n")
        handle.flush()
        proc = subprocess.Popen(argv, cwd=str(ROOT), env=env, stdout=handle,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    log(f"spawn drainer sub={sub} gpu={gpu} pid={proc.pid} log={log_path}")
    return proc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sub", action="append", default=[], choices=C.SUBS,
                        help="纳入调度的子检查（可重复）；默认全部 4 个")
    parser.add_argument("--workers", type=int, default=1, help="每卡 worker 数（1-2）")
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--max-hours", type=float, default=0.0, help=">0 时到点退出（0=不限）")
    parser.add_argument("--once", action="store_true", help="单轮干跑：只打印决策，不起 drainer")
    parser.add_argument("--force", action="store_true", help="忽略已存在的 scheduler.pid")
    args = parser.parse_args(argv)

    subs = args.sub or list(DEFAULT_SUB_ORDER)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if not args.once:
        if PID_PATH.exists() and not args.force:
            old = int((PID_PATH.read_text().strip() or "0") or 0)
            if pid_alive(old):
                log(f"refuse to start: scheduler.pid={old} still alive (use --force)")
                return 1
        PID_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")
        log(f"scheduler start pid={os.getpid()} subs={subs} workers={max(1, min(2, args.workers))} "
            f"poll={args.poll_seconds}s max_hours={args.max_hours or 'inf'} policy=gpu"
            f"{list(GPU_RANGE)} util<{FREE_UTIL_MAX}% mem<{FREE_MEM_MAX_MB}MiB "
            f"max_drainers={MAX_DRAINERS}")

    deadline = time.time() + args.max_hours * 3600 if args.max_hours > 0 else None
    state: dict[int, dict] = {}          # gpu -> {proc, sub, log}
    cooldown: dict[str, float] = {}      # sub -> 允许再次 spawn 的最早时刻（快速失败退避）
    poll_no = 0
    while True:
        poll_no += 1
        # 1) 回收自己起的 drainer
        for gpu, info in list(state.items()):
            rc = info["proc"].poll()
            if rc is None:
                continue
            log(f"drainer exit sub={info['sub']} gpu={gpu} rc={rc}")
            if rc != 0:
                cooldown[info["sub"]] = time.time() + 60.0
            del state[gpu]
        # 2) 队列状态（conf 数；running 计入"未清空"）
        status = {s: C.queue_status(s) for s in subs}
        work = {s: status[s]["queue"] + status[s]["running"] for s in subs}
        # 3) 全部清空且无 drainer -> 收工
        if not state and all(v == 0 for v in work.values()):
            if args.once:
                stats = gpu_stats()
                log(f"dry-run poll: status={status} "
                    f"free={[g for g in GPU_RANGE if is_free(stats, g)]} "
                    f"(queues empty; nothing to place)")
                return 0
            log(f"all subs drained {status} -> scheduler exit")
            if not args.once and PID_PATH.exists():
                PID_PATH.unlink()
            return 0
        # 4) 空闲卡（重新查询，逐卡判定）
        stats = gpu_stats()
        free = [g for g in GPU_RANGE if g not in state and is_free(stats, g)]
        active_subs = {info["sub"] for info in state.values()}
        now = time.time()
        placements = []
        for gpu in free:
            if len(state) >= MAX_DRAINERS:
                break
            cands = [s for s in subs if work[s] > 0 and s not in active_subs
                     and cooldown.get(s, 0.0) <= now]
            if not cands:
                break
            sub = max(cands, key=lambda s: work[s])   # 剩余最多的子检查优先
            if is_free(gpu_stats(), gpu):             # 放置前 re-check 同一张卡
                placements.append((gpu, sub))
                active_subs.add(sub)
            else:
                log(f"skip gpu={gpu}: busy on re-check")
        if args.once:
            log(f"dry-run poll: status={status} free={free} placements={placements}")
            return 0
        for gpu, sub in placements:
            proc = spawn_drainer(sub, gpu, max(1, min(2, args.workers)))
            state[gpu] = {"proc": proc, "sub": sub}
        # 5) 心跳：状态变化或每 10 轮打一行
        if placements or poll_no % 10 == 1:
            log(f"poll#{poll_no} status={status} active="
                f"{ {g: i['sub'] for g, i in state.items()} } free={free}")
        if deadline is not None and time.time() >= deadline:
            log(f"max-hours reached, scheduler exit (still active: "
                f"{ {g: i['sub'] for g, i in state.items()} })")
            if PID_PATH.exists():
                PID_PATH.unlink()
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
