"""Paths for the standalone PGC (SurvPGC) L0-L5 / D0-D5 line.

本线从 A_pipeline 复制独立而来,产物根改到 projects/outputs_pgc/,与 gdc 线
(projects/outputs/)完全隔离。无 landmark 协议,无 paper / Test_3 方案。
"""

from __future__ import annotations

import os
from pathlib import Path


A_PIPELINE_PGC_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = A_PIPELINE_PGC_ROOT.parent
REPO_ROOT = PROJECT_ROOT.parent
WORKSPACE_ROOT = REPO_ROOT.parent

# 本线唯一产物根(结构不变:outputs_pgc/{dataset}/A_manual/{scheme}/)。
OUTPUTS_ROOT = PROJECT_ROOT / "outputs_pgc"

DEFAULT_JSON_PATH = (
    "/data/lizhe/Medteam_projects/kindey_cancer_TCGA/clinical/clinical.cart.2026-03-17.json"
)
DEFAULT_DATASETS_CONFIG = str(A_PIPELINE_PGC_ROOT / "datasets.json")
DEFAULT_TEMPLATE_DIR = str(A_PIPELINE_PGC_ROOT / "templates")
DEFAULT_PROMPT_DIR = str(OUTPUTS_ROOT / "custom" / "A_manual")
DEFAULT_CKPT = str(WORKSPACE_ROOT / "CONCH" / "pytorch_model.bin")
DEFAULT_OUT_DIR = str(OUTPUTS_ROOT / "custom" / "A_manual")
DEFAULT_BASELINE_OUT_ROOT = str(OUTPUTS_ROOT)
DEFAULT_GPU = os.environ.get("A_PIPELINE_PGC_GPU", os.environ.get("A_PIPELINE_GPU", "7"))


def dataset_prompt_dir(dataset_name: str) -> str:
    return str(OUTPUTS_ROOT / dataset_name / "A_manual")


def dataset_embedding_dir(dataset_name: str) -> str:
    return str(OUTPUTS_ROOT / dataset_name / "A_manual")


def dataset_baseline_embedding_dir(dataset_name: str, base_root: str) -> str:
    return str(Path(base_root) / dataset_name / "A_manual")


def dataset_hgcn_clinic_dir(
    dataset_name: str,
    scheme: str | None = None,
    base_root: str | None = None,
) -> str:
    root = Path(base_root) if base_root else OUTPUTS_ROOT
    path = root / dataset_name / "A_manual" / "HGCN_clinic"
    if scheme:
        path = path / scheme
    return str(path)


def global_mapping_dir() -> Path:
    """本线只有一份共享词表(源=lizhe),没有 gdc/ 分支。"""
    return A_PIPELINE_PGC_ROOT / "baseline_onehot_mapping_tables"
