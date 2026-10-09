#!/bin/bash
# Test_6 试点调度器:24 个 (ds, algo) 搜索,4 槽位(GPU 0/1/2/3),每槽一次只跑一个搜索。
# 用法: bash scripts/t6_scheduler.sh          # 前台循环;nohup 后台跑日志到 /tmp/t6_scheduler.log
set -u
cd "$(cd "$(dirname "$0")/.." && pwd)"
SLOT_DIR="/tmp/t6_slots"
mkdir -p "$SLOT_DIR"
LOG="/tmp/t6_scheduler.log"
SLOTS="0 1 2 3 4 5 6 7"      # 槽位名:每卡 2 槽(4 卡 × 2 搜索并发)

gpu_for_slot() { echo $(( $1 % 4 )); }

pairs=""
for ds in TCGA-GBM TCGA-LGG TCGA-PAAD; do
  for algo in A1_random A3_beam A4_anneal A5_genetic A6_aco SEAS A0_full A0b_topk; do
    pairs="$pairs $ds/$algo"
  done
done

run_one() {
  local ds="$1" algo="$2" slot="$3"
  local gpu; gpu=$(gpu_for_slot "$slot")
  echo "[t6] $(date +%F_%T) slot=$slot(gpu$gpu) start $ds/$algo" >> "$LOG"
  env CUDA_VISIBLE_DEVICES="$gpu" python3 scripts/run_selection_queue.py \
    --dataset "$ds" --landmark_time 0 --algo "$algo" \
    --stop_mode gain_only --seed 0 --budget_cap 500 \
    --queue_root Clinic_Analyzer/configs/Test_6_search \
    --out "results/Test_6_search/prompt/landmark_0/$ds/$algo" \
    --workers 8 >> "$LOG" 2>&1
  echo "[t6] $(date +%F_%T) slot=$slot exit=$? done $ds/$algo" >> "$LOG"
  rmdir "$SLOT_DIR/slot$slot" 2>/dev/null
}

# 槽位获取:任一空闲槽即用(避免慢搜索队头阻塞后面的任务);mkdir 原子占位
acquire_any() {
  while true; do
    for slot in $SLOTS; do
      if mkdir "$SLOT_DIR/slot$slot" 2>/dev/null; then
        echo "$slot"
        return
      fi
    done
    sleep 30
  done
}

idx=0
for pair in $pairs; do
  ds="${pair%/*}"; algo="${pair#*/}"
  idx=$((idx + 1))
  slot=$(acquire_any)
  ( run_one "$ds" "$algo" "$slot" ) &
done
wait
echo "[t6] $(date +%F_%T) ALL 24 searches finished" >> "$LOG"
