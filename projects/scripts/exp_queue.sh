#!/bin/bash
# exp_queue.sh —— 实验队列统一入口(薄壳;业务逻辑全在 scripts/exp_queue.py)
#
# 只做两件事:
#   ① verb 与其余参数逐字透传(环境变量原样传递:GPU 用 CUDA_VISIBLE_DEVICES,
#     并发用 WORKERS,解释器用 PYTHON3)。
#   ② 长驻 verb 后台化(run / bank_bg):nohup 起、输出全进日志文件,
#     终端只回 PID / 日志路径 / 停止方式(同 SurvPGC bg_tune.sh 惯例)。
#
# 用法(projects/ 根目录):
#   bash scripts/exp_queue.sh list
#   bash scripts/exp_queue.sh status
#   bash scripts/exp_queue.sh enqueue  --arm test_1a_t0
#   CUDA_VISIBLE_DEVICES=7 WORKERS=16 bash scripts/exp_queue.sh run   # 后台;日志 RUN_LOG 可覆盖
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"

PY="${PYTHON3:-python3}"   # exp_queue.py 自身跑 base python3

VERB="${1:-}"
[ -n "$VERB" ] || { sed -n '2,16p' "$0"; exit 2; }
shift

case "$VERB" in
    run)
        if [ -n "${RUN_LOG:-}" ]; then
            log="$RUN_LOG"
        else
            log="results/logs/exp_queue_run_$(date +%F_%H%M%S)_$$.log"   # $$ 保证同秒多次启动不撞名
        fi
        mkdir -p "$(dirname "$log")" 2>/dev/null || true
        # setsid = run 自成一个进程组:kill PID 时子进程(训练子进程)一起收尸
        setsid "$PY" -u scripts/exp_queue.py run "$@" > "$log" 2>&1 &
        echo "[exp_queue] run PID $! (log: $log;停止: kill $!)"
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
