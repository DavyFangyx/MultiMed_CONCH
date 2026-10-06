#!/bin/bash
# S4 Test_2b 批跑投放 / 监控 / 续跑入口（R13：15 主集 x 4 泛癌种 + 4 HGCN 绑定 = 64 组合 x 2 臂 x 2 分析器 = 256 confs）
#
# 分工：
#   scripts/s4_enqueue.py   enqueue/summarize/status（不训练，python 3.13.12）
#   drainer 进程            scripts/run_a_manual.py cindex --workers N（claim conf -> Clinic_Analyzer/run.sh 训练）
#   encode 队列             本脚本 encode 模式（conch 环境，GPU 默认 7 = A_PIPELINE_GPU 的默认值）
#
# 用法（在 projects/ 根目录）：
#   bash scripts/s4_Test_2b_queue.sh encode              # 后台生成缺失的 embeddings（波1优先）
#   bash scripts/s4_Test_2b_queue.sh enqueue A1          # 投放波1 臂A 泛癌种 conf
#   bash scripts/s4_Test_2b_queue.sh drain               # 启动训练 drainer（GPU 5, 8 workers, 后台）
#   bash scripts/s4_Test_2b_queue.sh status              # 队列桶 + 编码队列进度
#   bash scripts/s4_Test_2b_queue.sh validate            # 首波校验（clinic_cox 逐位 diff + 字段表审计）
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
# 日志/pid 落 results/Test_2b/logs（原 A_pipeline/S4_*.log 随 A_pipeline 目录删除）
S4_LOG_DIR="${S4_LOG_DIR:-results/Test_2b/logs}"
mkdir -p "$S4_LOG_DIR"
ENCODE_LOG="$S4_LOG_DIR/S4_encode.log"
DRAIN_LOG="$S4_LOG_DIR/S4_drain.log"
DRAIN_PID="$S4_LOG_DIR/S4_drain.pid"
WATCH_LOG="$S4_LOG_DIR/S4_watch.log"
SUMMARY_LOG="$S4_LOG_DIR/S4_summary.log"
QUEUE_ROOT="$(pwd)/Clinic_Analyzer/configs/Test_2b_arms"

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
            conda run -n "$2" python scripts/run_a_manual.py pipeline \
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
    nohup env CUDA_VISIBLE_DEVICES="$GPU_TRAIN" $PYTHON3 scripts/run_a_manual.py cindex \
        --dataset TCGA-BRCA --scheme MULTISURV --landmark_time none \
        --encoding text --analyzer clinic_cox --workers "$WORKERS" \
        --queue_root "$QUEUE_ROOT" \
        > "$DRAIN_LOG" 2>&1 &
    echo $! > "$DRAIN_PID"
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
        root="$(pwd)/Clinic_Analyzer/configs/Test_2b_arms"
        waves="A1 A1H B1 B1H A2 B2 A3 B3"
        python3="$1"; gpu="$2"; workers="$3"
        watch_log="$4"; drain_pid="$5"; drain_log="$6"; summary_log="$7"
        last_sum=0
        while true; do
            q=$(ls "$root"/queue/*.conf 2>/dev/null | wc -l)
            r=$(ls "$root"/running/*.conf 2>/dev/null | wc -l)
            done_c=$(ls "$root"/done/*__landmark_*.conf 2>/dev/null | wc -l)
            now=$(date +%s)
            dpid=$(cat "$drain_pid" 2>/dev/null || true)
            alive=0
            if [ -n "$dpid" ] && kill -0 "$dpid" 2>/dev/null; then alive=1; fi
            if [ "$alive" -eq 0 ] && { [ "$q" -gt 0 ] || [ "$r" -gt 0 ]; }; then
                echo "[S4][watch] $(date +%F_%T) relaunch drainer (q=$q r=$r)" >> "$watch_log"
                env CUDA_VISIBLE_DEVICES="$gpu" $python3 scripts/run_a_manual.py cindex \
                    --dataset TCGA-BRCA --scheme MULTISURV --landmark_time none \
                    --encoding text --analyzer clinic_cox --workers "$workers" \
                    --queue_root "$root" \
                    >> "$drain_log" 2>&1 &
                echo $! > "$drain_pid"
                sleep 30
            fi
            if [ "$q" -eq 0 ] && [ "$r" -eq 0 ]; then
                enqueued=0
                for s in $waves; do
                    out=$($python3 scripts/s4_enqueue.py --slice "$s" 2>/dev/null | grep -o "created=[0-9]*" | head -1)
                    c=${out#created=}
                    if [ -n "$c" ] && [ "$c" -gt 0 ]; then
                        echo "[S4][watch] $(date +%F_%T) enqueue slice $s (+$c)" >> "$watch_log"
                        enqueued=1
                        break
                    fi
                done
                if [ "$done_c" -ge 552 ]; then
                    echo "[S4][watch] $(date +%F_%T) ALL 552 done" >> "$watch_log"
                    break
                fi
                if [ "$enqueued" -eq 0 ] && [ "$alive" -eq 0 ]; then
                    echo "[S4][watch] $(date +%F_%T) relaunch drainer" >> "$watch_log"
                    env CUDA_VISIBLE_DEVICES="$gpu" $python3 scripts/run_a_manual.py cindex \
                        --dataset TCGA-BRCA --scheme MULTISURV --landmark_time none \
                        --encoding text --analyzer clinic_cox --workers "$workers" \
                        --queue_root "$root" \
                        >> "$drain_log" 2>&1 &
                    echo $! > "$drain_pid"
                fi
                for s in $waves; do
                    $python3 scripts/s4_enqueue.py --slice "$s" --summarize >> "$summary_log" 2>&1
                done
                last_sum=$now
            elif [ $((now - last_sum)) -ge 300 ]; then
                for s in $waves; do
                    $python3 scripts/s4_enqueue.py --slice "$s" --summarize >> "$summary_log" 2>&1
                done
                last_sum=$now
            fi
            sleep 60
        done
    ' _ "$PYTHON3" "$GPU_TRAIN" "$WORKERS" "$WATCH_LOG" "$DRAIN_PID" "$DRAIN_LOG" "$SUMMARY_LOG" > /dev/null 2>&1 &
    echo "[S4] watch PID: $!  (log: $WATCH_LOG)"
}

case "${1:-}" in
    encode) cmd_encode ;;
    enqueue) cmd_enqueue "${2:?usage: s4_Test_2b_queue.sh enqueue <A1|A1H|B1|B1H|A2|B2|A3|B3>}" ;;
    drain) cmd_drain ;;
    watch) cmd_watch ;;
    status) cmd_status ;;
    validate) cmd_validate ;;
    *)
        echo "usage: bash scripts/s4_Test_2b_queue.sh {encode|enqueue <slice>|drain|watch|status|validate}"
        exit 2
        ;;
esac
