#!/bin/bash
# S5b / Test_1a off 臂 univariate 队列（raw 变体(mask off) x mlp_clinic_flatten x seed 0）
#
# R13（用户指令，2026-10-02）：off 臂训练范围限定 n_event >= 100 的 15 个 TCGA 数据集
#   （名单从 results/Test_0_dataset_availability/manifest.csv 的 n_event 派生，不硬编码；
#    同口径亦见 rawdata_stats/_shared/event_summary.csv；非主集任务用 `trim` 撤到 parked/，不删除）。
#
# 分工：
#   scripts/s5b_build_raw_field_bank.py     构建 raw Field Bank（conch env 编码，GPU 由 S5B_ENC_GPU 指定）
#   scripts/s5b_univariate_enqueue.py       enqueue/status/retry/recover/drain/watch/report（base python 3.13.12，不训练）
#   drainer 进程（每 GPU 一个，本脚本经 python helper 拉起）
#                                           scripts/run_univariate_cindex.py --landmark_time none --extraction_mask off ...
#                                           （自带队列：enqueue 幂等 + claim 一个 dataset 后跑完其全部字段）
#   watch 循环（python helper）               drainer 死后拉起 / failed 重试(≤3) / running 回收 / 全 done 后 report 退出
#
# 与 t0 臂的唯一差异（控制变量 = 取值 mask）：
#   raw 臂: --landmark_time none --extraction_mask off --label_tag landmark_0
#           --field_bank_root|--embeddings_root outputs/_raw  --results_dir results/univariate_raw
#           --queue_root Clinic_Analyzer/configs/univariate_raw
#
# 用法（在 projects/ 根目录）：
#   bash scripts/s5b_univariate_queue.sh bank        # 构建 raw field bank（前台；已存在的跳过）
#   bash scripts/s5b_univariate_queue.sh bank_bg     # 同上，后台（日志 /tmp/s5b_build.log）
#   bash scripts/s5b_univariate_queue.sh check       # 校验 R13 主集 raw bank 齐备
#   bash scripts/s5b_univariate_queue.sh enqueue     # 预投放主集 conf（幂等）
#   bash scripts/s5b_univariate_queue.sh trim        # R13：非主集任务撤到 parked/（不删除）
#   bash scripts/s5b_univariate_queue.sh drain       # 每 GPU 起一个后台 drainer
#   bash scripts/s5b_univariate_queue.sh watch       # 后台 watch 自愈循环（全完成自动 report 并退出）
#   bash scripts/s5b_univariate_queue.sh status      # 队列桶 + 每数据集 field_cindex.csv 行数
#   bash scripts/s5b_univariate_queue.sh report      # 最终汇总（并写 results/univariate_raw/_s5b_report.json）
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"

PYTHON3="${S5B_PYTHON3:-python3}"                                        # base 3.13.12（投放/监控，不训练）
CONCH_PYTHON="${S5B_CONCH_PYTHON:-/data/fangyuxuan/miniconda3/envs/conch/bin/python}"
GPUS="${S5B_GPUS:-7}"                                                    # 训练 GPU（drainer），逗号分隔
WORKERS="${S5B_WORKERS:-8}"                                              # 单 drainer 内并行字段数
ENC_GPU="${S5B_ENC_GPU:-7}"                                              # raw bank 编码 GPU
BUILD_LOG="${S5B_BUILD_LOG:-/tmp/s5b_build.log}"
WATCH_LOG="${S5B_WATCH_LOG:-/tmp/s5b_watch.log}"
export S5B_GPUS="$GPUS" S5B_WORKERS="$WORKERS" S5B_PYTHON3="$PYTHON3" S5B_WATCH_LOG="$WATCH_LOG"

cmd_bank() {
    env CUDA_VISIBLE_DEVICES="$ENC_GPU" "$CONCH_PYTHON" scripts/s5b_build_raw_field_bank.py --dataset all
}

cmd_bank_bg() {
    nohup env CUDA_VISIBLE_DEVICES="$ENC_GPU" "$CONCH_PYTHON" scripts/s5b_build_raw_field_bank.py --dataset all \
        > "$BUILD_LOG" 2>&1 &
    echo "[s5b] bank build PID $! (log: $BUILD_LOG)"
}

cmd_check() {
    "$PYTHON3" - <<'EOF'
import csv, sys
from pathlib import Path
sys.path.insert(0, "src")
from common.datasets import load_dataset_configs

manifest = Path("results/Test_0_dataset_availability/manifest.csv")
rows = list(csv.DictReader(open(manifest, encoding="utf-8")))
main = sorted(r["dataset"] for r in rows
              if r["dataset"].startswith(("TCGA-", "TCGA_")) and int(r["n_event"]) >= 100)
all_ds = sorted(n for n in load_dataset_configs("datasets.json") if n.startswith(("TCGA-", "TCGA_")))
missing = [n for n in main if not (Path("outputs/_raw") / n / "field_bank" / "prompt" / "landmark_none" / "field_index.json").exists()]
print(f"[s5b] R13 主集 raw banks: {len(main) - len(missing)}/{len(main)}  (全 TCGA 33 个中已建 {sum(1 for n in all_ds if (Path('outputs/_raw')/n/'field_bank'/'prompt'/'landmark_none'/'field_index.json').exists())})")
if missing:
    print(f"[s5b] missing: {missing}")
    raise SystemExit(1)
EOF
}

cmd_enqueue() { "$PYTHON3" scripts/s5b_univariate_enqueue.py enqueue --workers "$WORKERS" --gpus "$GPUS"; }
cmd_trim()    { "$PYTHON3" scripts/s5b_univariate_enqueue.py trim; }
cmd_drain()   { "$PYTHON3" scripts/s5b_univariate_enqueue.py drain   --workers "$WORKERS" --gpus "$GPUS"; }
cmd_status()  { "$PYTHON3" scripts/s5b_univariate_enqueue.py status  --workers "$WORKERS" --gpus "$GPUS"; }
cmd_report()  { "$PYTHON3" scripts/s5b_univariate_enqueue.py report; }
cmd_watch() {
    : > "$WATCH_LOG"
    nohup "$PYTHON3" scripts/s5b_univariate_enqueue.py watch --workers "$WORKERS" --gpus "$GPUS" \
        > /dev/null 2>&1 &
    echo "[s5b] watch PID $! (log: $WATCH_LOG)"
}

case "${1:-}" in
    bank) cmd_bank ;;
    bank_bg) cmd_bank_bg ;;
    check) cmd_check ;;
    enqueue) cmd_enqueue ;;
    trim) cmd_trim ;;
    drain) cmd_drain ;;
    watch) cmd_watch ;;
    status) cmd_status ;;
    report) cmd_report ;;
    *)
        echo "usage: bash scripts/s5b_univariate_queue.sh {bank|bank_bg|check|enqueue|trim|drain|watch|status|report}"
        exit 2
        ;;
esac
