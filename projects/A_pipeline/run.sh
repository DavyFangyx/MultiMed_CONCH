#!/bin/bash
# run.sh - A cindex foreground entry
# Same as: python A_pipeline/run.py cindex ...
# Scheduler prints to this terminal. Per-job training logs stay in
# results/A_manual/runs/{study}__{scheme}/{modality}/run.log
#
# Usage:
#   conda activate SurvPGC
#   cd CONCH-main/projects
#   CUDA_VISIBLE_DEVICES=2 bash A_pipeline/run.sh \
#       --workers 16 \
#       --dataset all \
#       --scheme manual \
#       --encoding text \
#       --modality mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECTS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECTS_ROOT"

PYTHON_BIN="${PYTHON_BIN:-python}"
export PYTHONUNBUFFERED=1

if [ "$#" -eq 0 ]; then
    echo "usage: bash A_pipeline/run.sh [cindex args...]"
    echo "example: CUDA_VISIBLE_DEVICES=2 bash A_pipeline/run.sh --workers 16 --dataset all --scheme manual --encoding text --modality mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten"
    exit 2
fi

exec "$PYTHON_BIN" A_pipeline/run.py cindex "$@"
