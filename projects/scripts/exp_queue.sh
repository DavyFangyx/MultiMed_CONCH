#!/bin/bash
# exp_queue.sh —— 实验队列统一入口（薄壳；业务逻辑全在 scripts/exp_queue.py，见 `list`）
#
# 本脚本只做两件事，verb 与其余参数逐字透传：
#   ① 环境变量透传：通用名 GPUS / GPU / WORKERS / ENC_GPU / PYTHON3 / CONCH_PYTHON
#      按臂前缀展开为 <PREFIX>GPUS / <PREFIX>WORKERS / …（已显式设置的 <PREFIX> 变量优先，
#      不会被覆盖）；兼容旧别名 S4_GPU_TRAIN -> S4_GPUS。
#   ② 长驻 verb 后台化：watch / scheduler / bank_bg 用 nohup 起（日志落点见输出行，
#      watch 类进程自身还会追加写臂注册表里的 <PREFIX>WATCH_LOG）。
#
# 用法（projects/ 根目录；`python3 scripts/exp_queue.py --help` 看 verb/参数，`list` 看臂名）：
#   bash scripts/exp_queue.sh list
#   bash scripts/exp_queue.sh status   --arm test_1a_off
#   WORKERS=8 GPUS=7 bash scripts/exp_queue.sh watch --arm test_1a_off
#   bash scripts/exp_queue.sh enqueue  --arm test_5_5E_2b
#   bash scripts/exp_queue.sh scheduler
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"

PY="${PYTHON3:-python3}"          # exp_queue.py 自身跑 base python3；各臂训练解释器在注册表里
PREFIXES="S5_ S5B_ S5C_ S4_ T3_ T5_ T6_"

# ① 通用名 -> <PREFIX>通用名（只填空，不覆盖显式设置的前缀变量）
for key in GPUS GPU WORKERS ENC_GPU PYTHON3 CONCH_PYTHON; do
    val="${!key:-}"
    [ -n "$val" ] || continue
    for p in $PREFIXES; do
        var="$p$key"
        [ -n "${!var:-}" ] || export "$var=$val"
    done
done
[ -n "${S4_GPU_TRAIN:-}" ] && [ -z "${S4_GPUS:-}" ] && export S4_GPUS="$S4_GPU_TRAIN"

# 后台化 verb 的日志落点：按 --arm 取前缀（仅为打印/重定向；不参与任何业务判断）
bg_log() {
    local arm="${1:-}"
    case "$arm" in
        t0|test_1a_t0|1a_t0)              echo "${S5_WATCH_LOG:-/tmp/s5_watch.log}" ;;
        off|test_1a_off|1a_off)            echo "${S5B_WATCH_LOG:-/tmp/s5b_watch.log}" ;;
        merged|test_1a_merged|1a_merged)   echo "${S5C_WATCH_LOG:-/tmp/s5c_watch.log}" ;;
        2b|test_2b|2b_arms)                echo "${S4_LOG_DIR:-results/Test_2b/logs}/S4_watch.log" ;;
        test_6_search|6search)             echo "${T6_WATCH_LOG:-/tmp/t6_scheduler.log}" ;;
        test_3_arms|3arms|3_arms|test_3_search|3search) \
                                           echo "${T3_WATCH_LOG:-results/Test_3_greedy_vs_works/logs/watch.log}" ;;
        *)                                 echo "${T5_WATCH_LOG:-results/Test_5_invariance/logs/scheduler.out}" ;;
    esac
}

VERB="${1:-}"
[ -n "$VERB" ] || { sed -n '2,28p' "$0"; exit 2; }
shift

first_arm=""
prev=""
for tok in "$@"; do
    case "$prev" in --arm|--arms) first_arm="${first_arm:-$tok}" ;; esac
    case "$tok" in --arm=*|--arms=*) first_arm="${first_arm:-${tok#*=}}" ;; esac
    prev="$tok"
done

case "$VERB" in
    watch|scheduler|bank_bg)
        run="$VERB"; [ "$VERB" = bank_bg ] && run="bank"
        log="$(bg_log "$first_arm")"
        mkdir -p "$(dirname "$log")" 2>/dev/null || true
        nohup "$PY" scripts/exp_queue.py "$run" "$@" >> "$log" 2>&1 &
        echo "[exp_queue] $run PID $! (log: $log)"
        ;;
    *)
        exec "$PY" scripts/exp_queue.py "$VERB" "$@"
        ;;
esac
