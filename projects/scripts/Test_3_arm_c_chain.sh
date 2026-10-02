#!/bin/bash
# S6 / Test_3 臂 C 自动接力：搜索 result.json 落盘即生成 → 编码 → 投放，全部就绪后 drained + 汇总 + 出三臂表
#
# 背景：搜索（Test_3_search_queue watch）可能跑数小时；臂 C 的位号来自各数据集 result.json 的
# recommended_subset（D4 sig_stop 参考点；历史最优 best_subset 由 result.json / search_summary.csv 同报，
# 需要时另跑 `Test_3_arms.py generate --arm best` 作附录）。本脚本轮询等待，避免人工守候。
#
# 纪律：只新增 Test_3_* 产物；GPU 避开 7（S5b 占用）；失败不退出，逐数据集记日志继续。
# 用法：nohup bash scripts/Test_3_arm_c_chain.sh > results/Test_3_greedy_vs_works/logs/arm_c_chain.log 2>&1 &
set -uo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"

PYTHON3="${T3_PYTHON3:-python3}"
ENC_GPU="${T3_ENC_GPU:-1}"
GPU="${T3_GPU:-1}"
POLL="${T3_POLL:-120}"
WORKERS="${T3_WORKERS:-2}"
LOG_ROOT=results/Test_3_greedy_vs_works/logs
mkdir -p "$LOG_ROOT"

echo "===== arm C chain start $(date '+%F %T') enc_gpu=$ENC_GPU train_gpu=$GPU ====="

mapfile -t DATASETS < <("$PYTHON3" -c "import sys; sys.path.insert(0, 'scripts'); import Test_3_common as C; print('\n'.join(C.main_datasets()))")
echo "[chain] datasets=${#DATASETS[@]}: ${DATASETS[*]}"

result_json() { echo "results/Test_3_greedy_vs_works/search/$1/mlp_clinic_flatten/seed_0/result.json"; }

pending=("${DATASETS[@]}")
while [ "${#pending[@]}" -gt 0 ]; do
    rest=()
    for ds in "${pending[@]}"; do
        if [ ! -f "$(result_json "$ds")" ]; then rest+=("$ds"); continue; fi
        echo "[chain] $ds result.json 落盘 $(date '+%F %T') → generate/encode/enqueue"
        "$PYTHON3" scripts/Test_3_arms.py generate --arm ksig --datasets "$ds" \
            || { echo "[chain] $ds generate 失败，保留待重试"; rest+=("$ds"); continue; }
        "$PYTHON3" scripts/Test_3_arms.py encode --arm ksig --gpu "$ENC_GPU" --parallel 2 --datasets "$ds" \
            || { echo "[chain] $ds encode 失败，保留待重试"; rest+=("$ds"); continue; }
        "$PYTHON3" scripts/Test_3_arms.py enqueue --arm ksig --datasets "$ds" \
            || { echo "[chain] $ds enqueue 失败，保留待重试"; rest+=("$ds"); continue; }
    done
    pending=("${rest[@]}")
    [ "${#pending[@]}" -gt 0 ] && sleep "$POLL"
done

echo "[chain] 15/15 臂 C 已投放，等待 B' 队列排空后开 drain $(date '+%F %T')"
"$PYTHON3" scripts/Test_3_arms.py drain --gpu "$GPU" --workers "$WORKERS"
echo "[chain] drain 结束 $(date '+%F %T')"

"$PYTHON3" scripts/Test_3_arms.py summarize --arm bp   || echo "[chain] summarize bp 失败"
"$PYTHON3" scripts/Test_3_arms.py summarize --arm ksig || echo "[chain] summarize ksig 失败"
"$PYTHON3" scripts/Test_3_compare.py --all             || echo "[chain] compare 失败"
echo "===== arm C chain done $(date '+%F %T') ====="
