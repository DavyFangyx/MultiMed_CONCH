"""Project paths shared by scheme and discovery workflows."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent
WORKSPACE_ROOT = REPO_ROOT.parent

DEFAULT_JSON_PATH = (
    "/data/lizhe/Medteam_projects/kindey_cancer_TCGA/clinical/clinical.cart.2026-03-17.json"
)
DEFAULT_DATASETS_CONFIG = str(PROJECT_ROOT / "datasets.json")
DEFAULT_TEMPLATE_DIR = str(PROJECT_ROOT / "templates/l0_l5")
DEFAULT_PROMPT_DIR = str(PROJECT_ROOT / "outputs/prompts")
DEFAULT_CKPT = str(WORKSPACE_ROOT / "CONCH/pytorch_model.bin")
DEFAULT_OUT_DIR = str(PROJECT_ROOT / "outputs/embeddings")
DEFAULT_BASELINE_OUT_ROOT = str(PROJECT_ROOT / "outputs")
DEFAULT_FIELD_BANK_TEMPLATE_DIR = PROJECT_ROOT / "templates/field_bank"
DEFAULT_JSON_FIELD_DICT = PROJECT_ROOT / "templates/common/json_field_dictionary.json"
LEGACY_JSON_FIELD_DICT = PROJECT_ROOT / "templates/l0_l5/json_field_dictionary.json"
REGISTRY_DIR = PROJECT_ROOT / "outputs" / "registry"
REGISTRY_DICTS_DIR = REGISTRY_DIR / "dicts"
TIME_STATS_ROOT = PROJECT_ROOT / "outputs" / "time_stats"

DEFAULT_GPU = "7"


def dataset_prompt_dir(dataset_name: str) -> str:
    return str(PROJECT_ROOT / "outputs" / dataset_name / "prompts")


def dataset_embedding_dir(dataset_name: str) -> str:
    return str(PROJECT_ROOT / "outputs" / dataset_name / "embeddings")


def dataset_stats_dir(dataset_name: str) -> Path:
    return PROJECT_ROOT / "outputs" / dataset_name / "stats"


def dataset_baseline_embedding_dir(dataset_name: str, base_root: str) -> str:
    return str(Path(base_root) / dataset_name / "embeddings")


def dataset_field_bank_dir(dataset_name: str) -> Path:
    return PROJECT_ROOT / "outputs" / dataset_name / "field_bank"


def dataset_greedy_dir(dataset_name: str) -> Path:
    return PROJECT_ROOT / "outputs" / dataset_name / "greedy"


def dataset_field_dict_path(dataset_name: str) -> Path:
    return REGISTRY_DICTS_DIR / f"{dataset_name}_json_field_dict.json"


def dataset_field_stats_path(dataset_name: str) -> Path:
    return REGISTRY_DIR / dataset_name / "field_stats_raw.csv"


def resolve_reference_dict_path(explicit=None) -> Path:
    if explicit:
        return Path(explicit)
    if DEFAULT_JSON_FIELD_DICT.exists():
        return DEFAULT_JSON_FIELD_DICT
    return LEGACY_JSON_FIELD_DICT
