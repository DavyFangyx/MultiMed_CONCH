"""Paths for the isolated A_manual L0-L5 / D0-D5 pipeline."""

from pathlib import Path


A_PIPELINE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = A_PIPELINE_ROOT.parent
REPO_ROOT = PROJECT_ROOT.parent
WORKSPACE_ROOT = REPO_ROOT.parent

DEFAULT_JSON_PATH = (
    "/data/lizhe/Medteam_projects/kindey_cancer_TCGA/clinical/clinical.cart.2026-03-17.json"
)
DEFAULT_DATASETS_CONFIG = str(A_PIPELINE_ROOT / "datasets.json")
DEFAULT_TEMPLATE_DIR = str(A_PIPELINE_ROOT / "templates")
DEFAULT_JSON_FIELD_DICT = str(A_PIPELINE_ROOT / "templates" / "json_field_dictionary.json")
DEFAULT_PROMPT_DIR = str(PROJECT_ROOT / "outputs" / "custom" / "A_manual")
DEFAULT_CKPT = str(WORKSPACE_ROOT / "CONCH" / "pytorch_model.bin")
DEFAULT_OUT_DIR = str(PROJECT_ROOT / "outputs" / "custom" / "A_manual")
DEFAULT_BASELINE_OUT_ROOT = str(PROJECT_ROOT / "outputs")
DEFAULT_GPU = "7"


def dataset_prompt_dir(dataset_name: str) -> str:
    return str(PROJECT_ROOT / "outputs" / dataset_name / "A_manual")


def dataset_embedding_dir(dataset_name: str) -> str:
    return str(PROJECT_ROOT / "outputs" / dataset_name / "A_manual")


def dataset_baseline_embedding_dir(dataset_name: str, base_root: str) -> str:
    return str(Path(base_root) / dataset_name / "A_manual")


def global_mapping_dir() -> Path:
    return A_PIPELINE_ROOT / "baseline_onehot_mapping_tables"
