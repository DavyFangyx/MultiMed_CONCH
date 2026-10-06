"""Paths for the manual (A_manual) pipeline: paper-scheme / custom-scheme encoding + cindex.

吸收自原独立子项目 ``A_pipeline/src/paths.py``：包内位置从 ``A_pipeline/src`` 变到
``src/manual_pipeline``，模板根从 ``A_pipeline/templates`` 变到 ``templates/manual_schemes``；
lizhe 数据源默认值（``DEFAULT_JSON_PATH`` / ``DEFAULT_DATASETS_CONFIG``）随 PGC 线走，本包不再有。
"""

from __future__ import annotations

import os
from pathlib import Path


MANUAL_PIPELINE_ROOT = Path(__file__).resolve().parents[0]           # projects/src/manual_pipeline
PROJECT_ROOT = MANUAL_PIPELINE_ROOT.parents[1]                        # projects
REPO_ROOT = PROJECT_ROOT.parent
WORKSPACE_ROOT = REPO_ROOT.parent

TEMPLATES_ROOT = PROJECT_ROOT / "templates" / "manual_schemes"

DEFAULT_GDC_DATASETS_CONFIG = str(PROJECT_ROOT / "datasets.json")
DEFAULT_TEMPLATE_DIR = str(TEMPLATES_ROOT)
DEFAULT_PROMPT_DIR = str(PROJECT_ROOT / "outputs" / "custom" / "A_manual")
DEFAULT_CKPT = str(WORKSPACE_ROOT / "CONCH" / "pytorch_model.bin")
DEFAULT_OUT_DIR = str(PROJECT_ROOT / "outputs" / "custom" / "A_manual")
DEFAULT_BASELINE_OUT_ROOT = str(PROJECT_ROOT / "outputs")
# encode 的可见 GPU：显式 --gpu > 环境变量 A_PIPELINE_GPU > 7
DEFAULT_GPU = os.environ.get("A_PIPELINE_GPU", "7")


def dataset_prompt_dir(dataset_name: str) -> str:
    return str(PROJECT_ROOT / "outputs" / dataset_name / "A_manual")


def dataset_embedding_dir(dataset_name: str) -> str:
    return str(PROJECT_ROOT / "outputs" / dataset_name / "A_manual")


def dataset_baseline_embedding_dir(dataset_name: str, base_root: str) -> str:
    return str(Path(base_root) / dataset_name / "A_manual")


def dataset_hgcn_clinic_dir(
    dataset_name: str,
    scheme: str | None = None,
    base_root: str | None = None,
) -> str:
    root = Path(base_root) if base_root else (PROJECT_ROOT / "outputs")
    path = root / dataset_name / "A_manual" / "HGCN_clinic"
    if scheme:
        path = path / scheme
    return str(path)


def global_mapping_dir(source: str | None = None) -> Path:
    """D 向量 one-hot 词表根。gdc 线只有 ``gdc`` 词表（lizhe 词表随 PGC 线走）。"""
    root = TEMPLATES_ROOT / "baseline_onehot_mapping_tables"
    if source and source != "lizhe":
        return root / source
    return root
