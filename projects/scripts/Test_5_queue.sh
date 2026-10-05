#!/bin/bash
# S12b / Test_5 不变性批跑总入口（E 轴 baseline / M 轴模型 × 15 主集）
#
# 内容（spec §8bis，口径见 scripts/Test_5_common.py 头注释）：
#   5E_2b  E→baseline 复现 Test_2b 两臂（A static_only / B landmark_0）× mlp_clinic_flatten
#   5E_3   E→baseline 复现 Test_3 臂 B′（Test_3_{work}_{ds}）/ C（Test_3_greedy_{ds}）
#   5M_2b  M→snn_clinic_flatten（15 主集）+ M→survgc_f/survpgc_f（BRCA/COAD/KIRC/LIHC）
#   5M_3   M→clinic_cox 复现 Test_3 臂 B′/C
#   产物：runs -> results/Test_5_invariance/{sub}/runs；表 -> results/Test_5_invariance/{sub}/{dataset}/
#   Q 轴重算：results_display/scripts/Test_5_q_recompute.py --merge（D7：dump vs 重算 diff=0）
#
# GPU 政策（硬约束）：只用 0-3 且放置时为空闲卡；4-7 不碰；最多 4 drainer；不 kill 他人进程。
#
# 用法（projects/ 根目录）：
#   bash scripts/Test_5_queue.sh enqueue            # 全部子检查入队（幂等，可重跑）
#   bash scripts/Test_5_queue.sh enqueue_one 5E_2b  # 单子检查入队
#   bash scripts/Test_5_queue.sh status             # 队列桶 + 期望数 + 缺编码
#   bash scripts/Test_5_queue.sh drain 1 5E_2b      # 单卡手动 drain（前台）
#   bash scripts/Test_5_queue.sh scheduler          # 后台多卡调度器（setsid nohup）
#   bash scripts/Test_5_queue.sh scheduler_stop     # 停调度器（只 kill 自己的 pid）
#   bash scripts/Test_5_queue.sh summarize          # 汇总（可反复跑）
#   bash scripts/Test_5_queue.sh q_recompute        # Q 轴重算 + dump/online diff（D7）
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"

PYTHON3="${T5_PYTHON3:-/data/fangyuxuan/miniconda3/envs/SurvPGC/bin/python}"   # 训练/汇总（SurvPGC env）
BASE_PYTHON3="${T5_BASE_PYTHON3:-python3}"                                    # base 3.13（enqueue/scheduler 亦可用）
CONCH_PYTHON="${T5_CONCH_PYTHON:-/data/fangyuxuan/miniconda3/envs/conch/bin/python}"
LOG_DIR="results/Test_5_invariance/logs"
mkdir -p "$LOG_DIR"

cmd_enqueue()        { nice -n 10 "$BASE_PYTHON3" scripts/Test_5_enqueue.py --sub all; }
cmd_enqueue_one()    { nice -n 10 "$BASE_PYTHON3" scripts/Test_5_enqueue.py --sub "$1" ${2:+--only "$2"}; }
cmd_status()         { nice -n 10 "$BASE_PYTHON3" scripts/Test_5_enqueue.py --status; }
cmd_list()           { nice -n 10 "$BASE_PYTHON3" scripts/Test_5_enqueue.py --list ${1:+--sub "$1"}; }
cmd_drain()          { local gpu="$1"; shift; nice -n 10 "$PYTHON3" -u scripts/Test_5_drain.py --gpu "$gpu" "$@"; }
cmd_scheduler() {
    setsid nohup nice -n 10 "$BASE_PYTHON3" -u scripts/Test_5_scheduler.py \
        --sub 5M_2b --sub 5E_2b --sub 5E_3 --sub 5M_3 --workers "${T5_WORKERS:-2}" \
        >> "$LOG_DIR/scheduler.out" 2>&1 &
    echo "[test_5] scheduler PID $! (log: $LOG_DIR/scheduler.out, $LOG_DIR/scheduler.log)"
}
cmd_scheduler_once() { nice -n 10 "$BASE_PYTHON3" scripts/Test_5_scheduler.py --once; }
cmd_scheduler_stop() {
    local pid_file="$LOG_DIR/scheduler.pid"
    [ -f "$pid_file" ] || { echo "[test_5] no scheduler.pid"; return 0; }
    local pid; pid="$(cat "$pid_file")"
    kill "$pid" && echo "[test_5] killed scheduler $pid"
}
cmd_summarize()      { nice -n 10 "$BASE_PYTHON3" scripts/Test_5_summarize.py --sub "${1:-all}"; }
cmd_baseline_c()     { nice -n 10 "$CONCH_PYTHON" scripts/Test_5_baseline_c.py --all; }
# Q 轴离线重算（D7：dump vs online diff=0）。输出默认写 /tmp——results_display/ 不在
# S12b 写权限内（Test_5_invariance/q_metrics.csv 现由 Test_2b 批次占用，4221 行）；
# 正式归档落点由 S13 决定，可用 T5_Q_OUT 覆盖。
cmd_q_recompute() {
    local out="${T5_Q_OUT:-/tmp/test_5_q_metrics.csv}"
    nice -n 10 "$PYTHON3" results_display/scripts/Test_5_q_recompute.py \
        --results-root results/Test_5_invariance --out "$out" --merge "$@"
    echo "[test_5] q_metrics -> $out"
}
cmd_all_status()     { cmd_status; echo "----"; nice -n 10 "$BASE_PYTHON3" scripts/Test_5_enqueue.py --status; }

case "${1:-}" in
    enqueue)         cmd_enqueue ;;
    enqueue_one)     shift; cmd_enqueue_one "$@" ;;
    status)          cmd_status ;;
    list)            shift; cmd_list "$@" ;;
    drain)           shift; cmd_drain "$@" ;;
    scheduler)       cmd_scheduler ;;
    scheduler_once)  cmd_scheduler_once ;;
    scheduler_stop)  cmd_scheduler_stop ;;
    summarize)       shift; cmd_summarize "$@" ;;
    baseline_c)      cmd_baseline_c ;;
    q_recompute)     shift; cmd_q_recompute "$@" ;;
    all_status)      cmd_all_status ;;
    *) sed -n '2,30p' "$0"; exit 1 ;;
esac
