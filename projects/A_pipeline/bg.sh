#!/bin/bash
# bg.sh - background A cindex; log file lands in A_pipeline/
# Scheduler output goes to this log. Per-job training logs stay in
# results/A_manual/runs/{study}__{scheme}/{modality}/run.log
#
# Usage:
#   CUDA_VISIBLE_DEVICES=2 bash A_pipeline/bg.sh AGPU2.log --workers 16 --dataset all --scheme manual --encoding text --modality mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten
set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "usage: CUDA_VISIBLE_DEVICES=N bash A_pipeline/bg.sh <log_file> [cindex args...]"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$1"
shift

if [[ "$LOG_FILE" != /* ]]; then
    LOG_FILE="$SCRIPT_DIR/$LOG_FILE"
fi

nohup bash "$SCRIPT_DIR/run.sh" "$@" > "$LOG_FILE" 2>&1 &
PID=$!

echo "PID: $PID"
echo "log: $LOG_FILE"
echo "stop: kill $PID"
