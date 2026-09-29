#!/bin/bash
# S4 H1b 批跑投放 / 监控 / 续跑入口（138 组合 x 2 臂 x 2 分析器 = 552 confs）
#
# 分工：
#   scripts/s4_enqueue.py   enqueue/summarize/status（不训练，python 3.13.12）
#   drainer 进程            A_pipeline/run.py cindex --workers N（claim conf -> Clinic_Analyzer/run.sh 训练）
#   encode 队列             本脚本 encode 模式（conch 环境，GPU 7 = A_pipeline DEFAULT_GPU）
#
# 用法（在 projects/ 根目录）：
#   bash scripts/s4_h1b_queue.sh encode              # 后台生成缺失的 embeddings（波1优先）
#   bash scripts/s4_h1b_queue.sh enqueue A1          # 投放波1 臂A 泛癌种 conf
#   bash scripts/s4_h1b_queue.sh drain               # 启动训练 drainer（GPU 5, 8 workers, 后台）
#   bash scripts/s4_h1b_queue.sh status              # 队列桶 + 编码队列进度
#   bash scripts/s4_h1b_queue.sh validate            # 首波校验（clinic_cox 逐位 diff + 字段表审计）
#
# 续跑：失败 conf 会在重跑 enqueue 时自动从 failed/ 重入队；drainer 退出后重跑 drain；
#       编码任务按产物存在性跳过（臂 A 已存在目录绝不重生成）。
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"

PYTHON3="${S4_PYTHON3:-python3}"                       # 3.13.12（硬条件 D3-1：汇总 std 用同一版本）
GPU_TRAIN="${S4_GPU_TRAIN:-5}"                         # 训练 GPU（drainer）
WORKERS="${S4_WORKERS:-8}"                             # 并发 claim 数
CONDA_ENCODE="${S4_CONDA_ENCODE:-conch}"               # 编码 conda 环境
ENCODE_PARALLEL="${S4_ENCODE_PARALLEL:-2}"             # 编码并行数（GPU 7）
ENCODE_LIST="/tmp/s4_encode_queue.tsv"
ENCODE_LOG="A_pipeline/S4_encode.log"
DRAIN_LOG="A_pipeline/S4_drain.log"
QUEUE_ROOT="Clinic_Analyzer/configs/A_manual"

cmd_encode() {
    $PYTHON3 scripts/s4_enqueue.py --emit-encodes | grep -E '^[123]\|TCGA' > "$ENCODE_LIST"
    local total; total=$(wc -l < "$ENCODE_LIST")
    echo "[S4] encode tasks: $total (list: $ENCODE_LIST)"
    if [ "$total" -le 0 ]; then echo "[S4] nothing to encode"; return 0; fi
    nohup bash -c '
        cat "$1" | while IFS="|" read -r wave ds scheme arm lm; do
            [ -z "$ds" ] && continue
            if [ "$arm" = "A" ]; then subdir=""; else subdir="landmark_0"; fi
            base="outputs/$ds/A_manual/$scheme${subdir:+/$subdir}"
            if [ -f "$base/prompts.csv" ] && [ -d "$base/embeddings/pt" ] && ls "$base/embeddings/pt"/*.pt >/dev/null 2>&1; then
                echo "[S4][encode] skip existing: $ds $scheme $arm"; continue
            fi
            conda run -n "$2" python A_pipeline/run.py pipeline \
                --dataset "$ds" --scheme "$scheme" --landmark_time "$lm" \
                >> "$3" 2>&1 \
                && echo "[S4][encode] done: $ds $scheme $arm" >> "$3" \
                || echo "[S4][encode] FAILED: $ds $scheme $arm" >> "$3"
        done
    ' _ "$ENCODE_LIST" "$CONDA_ENCODE" "$ENCODE_LOG" > /dev/null 2>&1 &
    echo "[S4] encode worker PID: $!  (log: $ENCODE_LOG, sequential)"
}

cmd_enqueue() {
    local slice="$1"
    $PYTHON3 scripts/s4_enqueue.py --slice "$slice"
}

cmd_drain() {
    # drainer：无新 conf 的调用（BRCA conf 已在 done/），只 claim 队列并训练。
    # 队列空且无 running 时退出；重跑本命令即可续跑。
    nohup env CUDA_VISIBLE_DEVICES="$GPU_TRAIN" $PYTHON3 A_pipeline/run.py cindex \
        --dataset TCGA-BRCA --scheme MULTISURV --landmark_time none \
        --encoding text --analyzer clinic_cox --workers "$WORKERS" \
        > "$DRAIN_LOG" 2>&1 &
    echo $! > A_pipeline/S4_drain.pid
    echo "[S4] drainer PID: $!  (GPU $GPU_TRAIN, workers $WORKERS, log: $DRAIN_LOG)"
    echo "[S4] stop: kill $!"
}

cmd_status() {
    for b in queue running done failed; do
        printf "%-8s %s confs\n" "$b" "$(ls "$QUEUE_ROOT/$b"/*.conf 2>/dev/null | wc -l)"
    done
    local d
    d=$(ls "$QUEUE_ROOT/done"/*__landmark_*.conf 2>/dev/null | wc -l)
    echo "done landmark confs: $d / 552"
    if [ -f "$ENCODE_LIST" ]; then
        local total left
        total=$(wc -l < "$ENCODE_LIST")
        left=0
        cat "$ENCODE_LIST" | while IFS="|" read -r wave ds scheme arm lm; do
            [ -z "$ds" ] && continue
            if [ "$arm" = "A" ]; then subdir=""; else subdir="landmark_0"; fi
            base="outputs/$ds/A_manual/$scheme${subdir:+/$subdir}"
            if ! { [ -f "$base/prompts.csv" ] && [ -d "$base/embeddings/pt" ] && ls "$base/embeddings/pt"/*.pt >/dev/null 2>&1; }; then
                echo left
            fi
        done | wc -l | xargs -I{} echo "encode tasks remaining: {} / $total"
    fi
}

cmd_validate() {
    $PYTHON3 scripts/s4_validate_firstwave.py
}

# watch：自动续跑（按协议 A 优先级分波投放；queue+running 空时投放下一波、
# drainer 退出时重启、每 5 分钟汇总已完成 run 的行；552 conf 全 done 后退出）。
# 手动续跑等价操作：s4_enqueue.py --slice <下一波> + 重跑 drain。
cmd_watch() {
    nohup bash -c '
        root="Clinic_Analyzer/configs/A_manual"
        waves="A1 A1H B1 B1H A2 B2 A3 B3"
        python3="$1"; gpu="$2"; workers="$3"
        last_sum=0
        while true; do
            q=$(ls "$root"/queue/*.conf 2>/dev/null | wc -l)
            r=$(ls "$root"/running/*.conf 2>/dev/null | wc -l)
            done_c=$(ls "$root"/done/*__landmark_*.conf 2>/dev/null | wc -l)
            now=$(date +%s)
            dpid=$(cat A_pipeline/S4_drain.pid 2>/dev/null || true)
            alive=0
            if [ -n "$dpid" ] && kill -0 "$dpid" 2>/dev/null; then alive=1; fi
            if [ "$alive" -eq 0 ] && { [ "$q" -gt 0 ] || [ "$r" -gt 0 ]; }; then
                echo "[S4][watch] $(date +%F_%T) relaunch drainer (q=$q r=$r)" >> A_pipeline/S4_watch.log
                env CUDA_VISIBLE_DEVICES="$gpu" $python3 A_pipeline/run.py cindex \
                    --dataset TCGA-BRCA --scheme MULTISURV --landmark_time none \
                    --encoding text --analyzer clinic_cox --workers "$workers" \
                    >> A_pipeline/S4_drain.log 2>&1 &
                echo $! > A_pipeline/S4_drain.pid
                sleep 30
            fi
            if [ "$q" -eq 0 ] && [ "$r" -eq 0 ]; then
                enqueued=0
                for s in $waves; do
                    out=$($python3 scripts/s4_enqueue.py --slice "$s" 2>/dev/null | grep -o "created=[0-9]*" | head -1)
                    c=${out#created=}
                    if [ -n "$c" ] && [ "$c" -gt 0 ]; then
                        echo "[S4][watch] $(date +%F_%T) enqueue slice $s (+$c)" >> A_pipeline/S4_watch.log
                        enqueued=1
                        break
                    fi
                done
                if [ "$done_c" -ge 552 ]; then
                    echo "[S4][watch] $(date +%F_%T) ALL 552 done" >> A_pipeline/S4_watch.log
                    break
                fi
                if [ "$enqueued" -eq 0 ] && [ "$alive" -eq 0 ]; then
                    echo "[S4][watch] $(date +%F_%T) relaunch drainer" >> A_pipeline/S4_watch.log
                    env CUDA_VISIBLE_DEVICES="$gpu" $python3 A_pipeline/run.py cindex \
                        --dataset TCGA-BRCA --scheme MULTISURV --landmark_time none \
                        --encoding text --analyzer clinic_cox --workers "$workers" \
                        >> A_pipeline/S4_drain.log 2>&1 &
                    echo $! > A_pipeline/S4_drain.pid
                fi
                for s in $waves; do
                    $python3 scripts/s4_enqueue.py --slice "$s" --summarize >> A_pipeline/S4_summary.log 2>&1
                done
                last_sum=$now
            elif [ $((now - last_sum)) -ge 300 ]; then
                for s in $waves; do
                    $python3 scripts/s4_enqueue.py --slice "$s" --summarize >> A_pipeline/S4_summary.log 2>&1
                done
                last_sum=$now
            fi
            sleep 60
        done
    ' _ "$PYTHON3" "$GPU_TRAIN" "$WORKERS" > /dev/null 2>&1 &
    echo "[S4] watch PID: $!  (log: A_pipeline/S4_watch.log)"
}

case "${1:-}" in
    encode) cmd_encode ;;
    enqueue) cmd_enqueue "${2:?usage: s4_h1b_queue.sh enqueue <A1|A1H|B1|B1H|A2|B2|A3|B3>}" ;;
    drain) cmd_drain ;;
    watch) cmd_watch ;;
    status) cmd_status ;;
    validate) cmd_validate ;;
    *)
        echo "usage: bash scripts/s4_h1b_queue.sh {encode|enqueue <slice>|drain|watch|status|validate}"
        exit 2
        ;;
esac
