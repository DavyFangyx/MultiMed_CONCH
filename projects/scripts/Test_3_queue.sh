#!/bin/bash
# S6 / Test_3 字段轴链队列（搜索 + 三臂对照）总入口
#
# 内容（spec §7）：A2_greedy × landmark_0 × mlp_clinic_flatten × seed 0，
#   早停 D4：gain < 0.005 且配对 Wilcoxon p >= 0.05 连续 3 步（同时上报历史最优）。
#   产物：results/Test_3_greedy_vs_works/{search/,compare/,three_arm.csv,missed_fields.csv,search_summary.csv}
#
# 分工（全部 base python 3.13.12；训练由各自队列内部拉起 SurvPGC/conch）：
#   scripts/Test_3_search_queue.py   enqueue/status/recover/retry/drain/watch/report（每数据集一条 selection 队列作业）
#   scripts/Test_3_arms.py           generate/encode/enqueue/drain/summarize/status（臂 B' / 臂 C 自定义方案 × A_pipeline cindex）
#     - encode 需 conch env python（编码 CONCH 文本嵌入）；其余命令 base python。
#     - A_pipeline 的两处缺口（方案白名单 / DEFAULT_GPU=7）由 scripts/Test_3_pipeline_one.py 进程内补，不改其源文件。
#   scripts/Test_3_compare.py        三臂 c-index 总表 + 遗漏字段清单（头条 Δc = C − B'）
#
# R13（用户指令，2026-10-02）：训练范围 = n_event >= 100 的 15 个主集（名单从
#   results/Test_0_dataset_availability/manifest.csv 与 rawdata_stats/_shared/event_summary.csv
#   派生并交叉核对，不硬编码）。
#
# 用法（在 projects/ 根目录）：
#   bash scripts/Test_3_queue.sh search_enqueue       # 预投放 15 主集搜索 conf（幂等）
#   bash scripts/Test_3_queue.sh search_watch         # 后台 watch 自愈（全 done 自动 report 退出）
#   bash scripts/Test_3_queue.sh search_status        # 搜索队列桶 + 每数据集进度
#   bash scripts/Test_3_queue.sh arms_generate        # 生成臂 B' 自定义方案（注册进 schemes.json）
#   bash scripts/Test_3_queue.sh arms_encode_bg       # 后台编码全部臂 B'（conch env，GPU 由 T3_ENC_GPU）
#   bash scripts/Test_3_queue.sh arms_enqueue         # 投放臂 B' cindex conf（幂等）
#   bash scripts/Test_3_queue.sh arms_drain           # 臂 B' cindex drainer（GPU 由 T3_GPU）
#   bash scripts/Test_3_queue.sh arms_generate_c      # 生成臂 C（需各数据集搜索 result.json 已落盘）
#   bash scripts/Test_3_queue.sh compare              # 三臂总表（缺臂记 pending，不中断）
#   bash scripts/Test_3_queue.sh all_status           # 搜索 + 三臂一屏状态
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"

PYTHON3="${T3_PYTHON3:-python3}"                                          # base 3.13.12
CONCH_PYTHON="${T3_CONCH_PYTHON:-/data/fangyuxuan/miniconda3/envs/conch/bin/python}"
SEARCH_GPUS="${T3_SEARCH_GPUS:-1,0,3,4,5,6,4,5,3}"                        # 搜索 drainer 槽位（避开 GPU 7=S5b）
ENC_GPU="${T3_ENC_GPU:-1}"                                                # 编码 GPU（CONCH，显存小）
GPU="${T3_GPU:-1}"                                                        # 三臂 cindex 训练 GPU
INTERVAL="${T3_INTERVAL:-60}"
WORKERS="${T3_WORKERS:-2}"                                                # arms drain 并发
PARALLEL="${T3_PARALLEL:-3}"                                              # arms encode 并发进程
WATCH_LOG="${T3_WATCH_LOG:-results/Test_3_greedy_vs_works/logs/watch.log}"
ENC_LOG="${T3_ENC_LOG:-results/Test_3_greedy_vs_works/logs/arms_encode_batch.log}"
mkdir -p results/Test_3_greedy_vs_works/logs

cmd_search_enqueue() { "$PYTHON3" scripts/Test_3_search_queue.py enqueue  --gpus "$SEARCH_GPUS"; }
cmd_search_status()  { "$PYTHON3" scripts/Test_3_search_queue.py status   --gpus "$SEARCH_GPUS"; }
cmd_search_recover() { "$PYTHON3" scripts/Test_3_search_queue.py recover; }
cmd_search_report()  { "$PYTHON3" scripts/Test_3_search_queue.py report; }
cmd_search_watch() {
    nohup "$PYTHON3" scripts/Test_3_search_queue.py watch --gpus "$SEARCH_GPUS" --interval "$INTERVAL" \
        > "$WATCH_LOG" 2>&1 &
    echo "[test_3] search watch PID $! (log: $WATCH_LOG)"
}

cmd_arms_generate()   { "$PYTHON3" scripts/Test_3_arms.py generate --arm bp; }
cmd_arms_generate_c() { "$PYTHON3" scripts/Test_3_arms.py generate --arm ksig; }
cmd_arms_encode()     { "$PYTHON3" scripts/Test_3_arms.py encode   --arm bp --gpu "$ENC_GPU" --parallel "$PARALLEL"; }
cmd_arms_encode_bg() {
    nohup "$PYTHON3" scripts/Test_3_arms.py encode --arm bp --gpu "$ENC_GPU" --parallel "$PARALLEL" \
        > "$ENC_LOG" 2>&1 &
    echo "[test_3] arms encode PID $! (log: $ENC_LOG)"
}
cmd_arms_enqueue()    { "$PYTHON3" scripts/Test_3_arms.py enqueue  --arm bp; }
cmd_arms_drain()      { "$PYTHON3" scripts/Test_3_arms.py drain    --gpu "$GPU" --workers "$WORKERS"; }
cmd_arms_status()     { "$PYTHON3" scripts/Test_3_arms.py status   --arm "${T3_ARM:-bp}"; }
cmd_arms_summarize()  { "$PYTHON3" scripts/Test_3_arms.py summarize --arm bp; }

cmd_compare()      { "$PYTHON3" scripts/Test_3_compare.py --all; }
cmd_all_status()   { cmd_search_status; echo "----"; cmd_arms_status; }

case "${1:-}" in
    search_enqueue)  cmd_search_enqueue ;;
    search_status)   cmd_search_status ;;
    search_recover)  cmd_search_recover ;;
    search_report)   cmd_search_report ;;
    search_watch)    cmd_search_watch ;;
    arms_generate)   cmd_arms_generate ;;
    arms_generate_c) cmd_arms_generate_c ;;
    arms_encode)     cmd_arms_encode ;;
    arms_encode_bg)  cmd_arms_encode_bg ;;
    arms_enqueue)    cmd_arms_enqueue ;;
    arms_drain)      cmd_arms_drain ;;
    arms_summarize)  cmd_arms_summarize ;;
    compare)         cmd_compare ;;
    all_status)      cmd_all_status ;;
    *)
        echo "usage: bash scripts/Test_3_queue.sh {search_enqueue|search_status|search_recover|search_report|search_watch|arms_generate|arms_generate_c|arms_encode|arms_encode_bg|arms_enqueue|arms_drain|arms_summarize|compare|all_status}"
        exit 2
        ;;
esac
