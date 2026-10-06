#!/usr/bin/env python3
"""A_manual 人工方案管线的唯一入口（原 A_pipeline/run.py + run.sh + bg.sh 的合并替代）。

六个子命令与旧 A_pipeline 完全同义：json2prompt / encode / pipeline / baseline /
hgcn_clinic / cindex。内核在 src/manual_pipeline/，方案模板在 templates/manual_schemes/。

用法（在 projects/ 根目录执行）：
  # 编码：JSON → prompt CSV → CONCH 文本塔 embedding（需 conch conda 环境）
  python scripts/run_a_manual.py pipeline --dataset TCGA-BRCA --scheme MULTISURV
  python scripts/run_a_manual.py json2prompt --dataset TCGA-BRCA --scheme MULTISURV
  python scripts/run_a_manual.py encode --dataset TCGA-BRCA --scheme MULTISURV --gpu 1

  # D 向量（baseline one-hot / 连续 / 有序）
  python scripts/run_a_manual.py baseline --dataset all --scheme paper

  # HGCN clinic 图节点 pkl（论文方案 / Test_3_* 自定义方案请显式点名）
  python scripts/run_a_manual.py hgcn_clinic --dataset TCGA-KIRC --scheme HGCN_KIRC

  # cindex 投递：conf 写 Clinic_Analyzer/configs/Test_3_arms/{queue,running,done,failed}，
  # 再由本进程 claim + Clinic_Analyzer/run.sh 训练；多开终端即并行抢活。
  CUDA_VISIBLE_DEVICES=2 python scripts/run_a_manual.py cindex \
      --dataset TCGA-BRCA --scheme MULTISURV --encoding text \
      --analyzer clinic_cox --workers 8

后台跑（等价旧 `bash A_pipeline/bg.sh <log>`，调度日志进指定文件）：
  nohup python scripts/run_a_manual.py cindex ... > A_drain.log 2>&1 & echo $! > A_drain.pid

编码 GPU（--gpu）优先于环境变量 A_PIPELINE_GPU，再默认 7，写进 CUDA_VISIBLE_DEVICES；
cindex 训练用各终端自己的 CUDA_VISIBLE_DEVICES，不受 --gpu 影响。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
SRC = PROJECT_ROOT / "src"

for path in (REPO_ROOT, SRC):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from manual_pipeline.cli import main


if __name__ == "__main__":
    main()
