#!/usr/bin/env python3
"""Test_5 队列 drainer：在指定 GPU 上按顺序 drain 一个/多个子检查的队列。

设计要点：
  * 只 claim + 跑 Clinic_Analyzer/run.sh；run/表落点由 conf 里的 EXP_GROUP= 决定
    （enqueue 时已写成 results/Test_5_invariance/{sub}/runs），drainer 不需要打补丁；
  * CUDA_VISIBLE_DEVICES 由本进程 env 传给子进程（run.sh 继承，写进 effective_config）；
  * 队列空且无 running 时自动退出（重跑本命令即可续跑；reuse=True 复用已完成 run dir）；
  * 队列根不存在时自动建目录（避免 drainer 先于 enqueue 启动时报错）。

用法（projects/ 根目录，SurvPGC env python3；务必 nice -n 10）：
  nice -n 10 python3 scripts/Test_5_drain.py --gpu 1 --sub 5M_2b
  nice -n 10 python3 scripts/Test_5_drain.py --gpu 1 --sub 5E_3 --sub 5M_3 --workers 2
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import Test_5_common as C  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu", required=True, help="物理卡号（本轮只用 0-3）")
    parser.add_argument("--sub", action="append", default=[], choices=C.SUBS,
                        help="子检查，可重复；默认按 5M_2b,5E_2b,5E_3,5M_3 顺序全排")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true", help="只打印队列计数，不 drain")
    args = parser.parse_args(argv)

    subs = args.sub or ["5M_2b", "5E_2b", "5E_3", "5M_3"]
    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu)

    from src.cindex import drain_queue, ensure_queue_dirs

    print(f"[test_5][drain] gpu={args.gpu} subs={subs} workers={max(1, args.workers)} "
          f"pid={os.getpid()}", flush=True)
    for sub in subs:
        root = C.queue_root(sub)
        if args.dry_run:
            print(f"[test_5][drain] {sub} {C.queue_status(sub)} root={root}", flush=True)
            continue
        root = ensure_queue_dirs(root)
        print(f"[test_5][drain] ==== {sub} start {C.queue_status(sub)} root={root}", flush=True)
        drain_queue(root, reuse=True, poll_seconds=args.poll_seconds,
                    workers=max(1, args.workers))
        print(f"[test_5][drain] ==== {sub} end {C.queue_status(sub)}", flush=True)
    print("[test_5][drain] all requested queues drained (or empty), exit", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
