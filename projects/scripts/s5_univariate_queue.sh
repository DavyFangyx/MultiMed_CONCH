#!/bin/bash
# S5 univariate 补跑队列（33 TCGA x landmark_0 x mlp_clinic_flatten x seed 0）
#
# 分工：
#   scripts/s5_univariate_enqueue.py   enqueue/status/retry/recover/report（base python 3.13.12，不训练）
#   drainer 进程（每 GPU 一个）        scripts/run_univariate_cindex.py --landmark_time 0 ...
#                                     （自带队列：enqueue 幂等 + claim 一个 dataset 后跑完其全部字段）
#   watch 循环                         drainer 死后拉起 / failed 重试(≤3) / 全 done 后汇总退出
#
# 用法（在 projects/ 根目录）：
#   bash scripts/s5_univariate_queue.sh enqueue    # 预投放 33 个 conf（幂等）
#   bash scripts/s5_univariate_queue.sh drain      # 每 GPU 起一个后台 drainer
#   bash scripts/s5_univariate_queue.sh watch      # 后台 watch 循环（自动续跑，全完成退出）
#   bash scripts/s5_univariate_queue.sh status     # 队列桶 + 每数据集 field_cindex.csv 行数
#   bash scripts/s5_univariate_queue.sh report     # 最终汇总
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"

PYTHON3="${S5_PYTHON3:-python3}"           # base 3.13.12（投放/监控，不训练）
GPUS="${S5_GPUS:-2,3,4}"                   # 训练 GPU（drainer），逗号分隔
WORKERS="${S5_WORKERS:-8}"                 # 单 drainer 内并行字段数
QUEUE_ROOT="Clinic_Analyzer/configs/univariate"
EXPECTED=33
PID_DIR="/tmp/s5_univariate"
DRAIN_LOG="/tmp/s5_drain.log"
WATCH_LOG="/tmp/s5_watch.log"
DS_LIST="$(python3 - <<'EOF'
import sys
sys.path.insert(0, "src")
from common.datasets import load_dataset_configs
names = [n for n in load_dataset_configs("datasets.json") if n.startswith("TCGA-") or n.startswith("TCGA_")]
print(",".join(sorted(names)))
EOF
)"
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 BLIS_NUM_THREADS=1

cmd_enqueue() {
    "$PYTHON3" scripts/s5_univariate_enqueue.py enqueue --workers "$WORKERS"
}

_start_drainer() {
    local gpu="$1"
    mkdir -p "$PID_DIR"
    nohup env CUDA_VISIBLE_DEVICES="$gpu" "$PYTHON3" scripts/run_univariate_cindex.py \
        --dataset "$DS_LIST" \
        --landmark_time 0 \
        --encoding prompt \
        --analyzer mlp_clinic_flatten \
        --seed 0 \
        --workers "$WORKERS" \
        >> "$DRAIN_LOG" 2>&1 &
    echo $! > "$PID_DIR/gpu${gpu}.pid"
    echo "[S5] drainer GPU $gpu PID $(cat "$PID_DIR/gpu${gpu}.pid")"
}

cmd_drain() {
    : > "$DRAIN_LOG"
    IFS=',' read -ra GARR <<< "$GPUS"
    for gpu in "${GARR[@]}"; do
        _start_drainer "$gpu"
    done
    echo "[S5] drainers: $(printf '%s ' "${GARR[@]}") workers=$WORKERS log=$DRAIN_LOG"
}

_drainer_alive() {
    local gpu="$1"
    [ -f "$PID_DIR/gpu${gpu}.pid" ] && kill -0 "$(cat "$PID_DIR/gpu${gpu}.pid")" 2>/dev/null
}

cmd_watch() {
    mkdir -p "$PID_DIR"
    IFS=',' read -ra GARR <<< "$GPUS"
    export DS_LIST
    : > "$WATCH_LOG"
    nohup bash -c '
        gpus="$1"; workers="$2"; expected="$3"; python3="$4"
        IFS="," read -ra GARR <<< "$gpus"
        last_sum=0
        while true; do
            q=$(ls '"$QUEUE_ROOT"'/queue/*.conf 2>/dev/null | wc -l)
            r=$(ls '"$QUEUE_ROOT"'/running/*.conf 2>/dev/null | wc -l)
            done_c=$(ls '"$QUEUE_ROOT"'/done/*__landmark_0.conf 2>/dev/null | wc -l)
            now=$(date +%s)
            "$python3" scripts/s5_univariate_enqueue.py recover >/dev/null 2>&1
            "$python3" scripts/s5_univariate_enqueue.py retry >/dev/null 2>&1
            if [ "$q" -gt 0 ]; then
                for gpu in "${GARR[@]}"; do
                    pidfile="'"$PID_DIR"'/gpu${gpu}.pid"
                    if ! { [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; }; then
                        echo "[S5][watch] $(date +%F_%T) relaunch drainer GPU $gpu (q=$q r=$r)" >> '"$WATCH_LOG"'
                        nohup env CUDA_VISIBLE_DEVICES="$gpu" "$python3" scripts/run_univariate_cindex.py \
                            --dataset "$DS_LIST" --landmark_time 0 --encoding prompt \
                            --analyzer mlp_clinic_flatten --seed 0 --workers "$workers" \
                            >> '"$DRAIN_LOG"' 2>&1 &
                        echo $! > "$pidfile"
                    fi
                done
            fi
            if [ "$done_c" -ge "$expected" ] && [ "$q" -eq 0 ] && [ "$r" -eq 0 ]; then
                echo "[S5][watch] $(date +%F_%T) ALL $expected done" >> '"$WATCH_LOG"'
                "$python3" scripts/s5_univariate_enqueue.py report >> '"$WATCH_LOG"' 2>&1
                break
            fi
            if [ $((now - last_sum)) -ge 300 ]; then
                "$python3" scripts/s5_univariate_enqueue.py status >> '"$WATCH_LOG"' 2>&1
                last_sum=$now
            fi
            sleep 60
        done
    ' _ "$GPUS" "$WORKERS" "$EXPECTED" "$PYTHON3" > /dev/null 2>&1 &
    echo "[S5] watch PID: $!  (log: $WATCH_LOG)"
}

cmd_status() {
    "$PYTHON3" scripts/s5_univariate_enqueue.py status --workers "$WORKERS"
}

cmd_report() {
    "$PYTHON3" scripts/s5_univariate_enqueue.py report
}

case "${1:-}" in
    enqueue) cmd_enqueue ;;
    drain) cmd_drain ;;
    watch) cmd_watch ;;
    status) cmd_status ;;
    report) cmd_report ;;
    *)
        echo "usage: bash scripts/s5_univariate_queue.sh {enqueue|drain|watch|status|report}"
        exit 2
        ;;
esac
