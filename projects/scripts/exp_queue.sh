#!/bin/bash
# exp_queue.sh —— 实验队列统一入口(薄壳;业务逻辑全在 scripts/exp_queue.py)
#
# 只做两件事:
#   ① verb 与其余参数逐字透传(环境变量原样传递:GPU 用 CUDA_VISIBLE_DEVICES,
#     并发用 WORKERS,解释器用 PYTHON3——不再有任何按臂前缀展开)。
#   ② 长驻 verb 后台化:scheduler / bank_bg 用 nohup 起。
#
# 用法(projects/ 根目录):
#   bash scripts/exp_queue.sh list
#   bash scripts/exp_queue.sh status   --arm test_1a_off
#   bash scripts/exp_queue.sh enqueue  --arm test_1a_t0
#   CUDA_VISIBLE_DEVICES=7 WORKERS=8 bash scripts/exp_queue.sh drain --arm test_1a_off
#   bash scripts/exp_queue.sh scheduler
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"

PY="${PYTHON3:-python3}"   # exp_queue.py 自身跑 base python3

VERB="${1:-}"
[ -n "$VERB" ] || { sed -n '2,16p' "$0"; exit 2; }
shift

case "$VERB" in
    scheduler)
        log="results/Test_5_invariance/logs/scheduler.out"
        mkdir -p "$(dirname "$log")" 2>/dev/null || true
        nohup "$PY" scripts/exp_queue.py scheduler "$@" >> "$log" 2>&1 &
        echo "[exp_queue] scheduler PID $! (log: $log)"
        ;;
    bank_bg)
        log="/tmp/raw_bank_build.log"
        mkdir -p "$(dirname "$log")" 2>/dev/null || true
        nohup "$PY" scripts/exp_queue.py bank "$@" >> "$log" 2>&1 &
        echo "[exp_queue] bank PID $! (log: $log)"
        ;;
    *)
        exec "$PY" scripts/exp_queue.py "$VERB" "$@"
        ;;
esac
