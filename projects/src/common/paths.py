"""Project paths shared by scheme and discovery workflows."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent
WORKSPACE_ROOT = REPO_ROOT.parent

DEFAULT_JSON_PATH = (
    str(PROJECT_ROOT / "ClinicDatasets" / "gdc_clinical" / "raw_json" / "TCGA-BRCA.json")
)
DEFAULT_DATASETS_CONFIG = str(PROJECT_ROOT / "datasets.json")
DEFAULT_TEMPLATE_DIR = str(PROJECT_ROOT / "templates/A_manual")
DEFAULT_PROMPT_DIR = str(PROJECT_ROOT / "outputs/custom/A_manual")
DEFAULT_CKPT = str(WORKSPACE_ROOT / "CONCH/pytorch_model.bin")
DEFAULT_OUT_DIR = str(PROJECT_ROOT / "outputs/custom/A_manual")
DEFAULT_BASELINE_OUT_ROOT = str(PROJECT_ROOT / "outputs")
DEFAULT_FIELD_BANK_TEMPLATE_DIR = PROJECT_ROOT / "templates" / "B_scan"
DEFAULT_JSON_FIELD_DICT = PROJECT_ROOT / "templates" / "field_labels.json"
LEGACY_JSON_FIELD_DICT = PROJECT_ROOT / "templates" / "common" / "json_field_dictionary.json"
RAWDATA_STATS_ROOT = PROJECT_ROOT / "rawdata_stats"
RAWDATA_STATS_SHARED_DIR = RAWDATA_STATS_ROOT / "_shared"
REGISTRY_DIR = RAWDATA_STATS_SHARED_DIR
REGISTRY_DICTS_DIR = RAWDATA_STATS_ROOT
TIME_STATS_ROOT = RAWDATA_STATS_ROOT

DEFAULT_GPU = "7"


def dataset_prompt_dir(dataset_name: str) -> str:
    return str(PROJECT_ROOT / "outputs" / dataset_name / "A_manual")


def dataset_embedding_dir(dataset_name: str) -> str:
    return str(PROJECT_ROOT / "outputs" / dataset_name / "A_manual")


def dataset_stats_dir(dataset_name: str) -> Path:
    return RAWDATA_STATS_ROOT / dataset_name


def dataset_manual_dir(dataset_name: str) -> Path:
    return PROJECT_ROOT / "outputs" / dataset_name / "A_manual"


def dataset_scheme_dir(dataset_name: str, scheme: str) -> Path:
    return dataset_manual_dir(dataset_name) / scheme


def dataset_baseline_embedding_dir(dataset_name: str, base_root: str) -> str:
    return str(Path(base_root) / dataset_name / "A_manual")


def dataset_field_bank_dir(dataset_name: str) -> Path:
    return PROJECT_ROOT / "outputs" / dataset_name / "B_scan" / "FIELD_BANK"


def dataset_greedy_dir(dataset_name: str) -> Path:
    return PROJECT_ROOT / "outputs" / dataset_name / "B_scan" / "greedy"


def dataset_field_bank_template_dir(dataset_name: str) -> Path:
    return DEFAULT_FIELD_BANK_TEMPLATE_DIR / dataset_name


def dataset_field_dict_path(dataset_name: str) -> Path:
    return RAWDATA_STATS_ROOT / dataset_name / "scanned_fields.json"


def dataset_field_stats_path(dataset_name: str) -> Path:
    return RAWDATA_STATS_ROOT / dataset_name / "field_stats.csv"


def dataset_kept_fields_path(dataset_name: str) -> Path:
    return RAWDATA_STATS_ROOT / dataset_name / "kept_fields.json"


def shared_kept_fields_path() -> Path:
    return RAWDATA_STATS_SHARED_DIR / "kept_fields.json"


def shared_field_stats_path() -> Path:
    return RAWDATA_STATS_SHARED_DIR / "field_stats.csv"


def dataset_filter_log_dir(dataset_name: str) -> Path:
    return RAWDATA_STATS_ROOT / dataset_name / "fliter_log"


def dataset_exclusion_log_path(dataset_name: str) -> Path:
    return dataset_filter_log_dir(dataset_name) / "exclusion_log.csv"


def dataset_field_registry_path(dataset_name: str) -> Path:
    return dataset_filter_log_dir(dataset_name) / "field_registry.csv"


def global_mapping_dir() -> Path:
    return PROJECT_ROOT / "outputs" / "_shared" / "A_manual" / "baseline_onehot_mapping_tables"


def resolve_reference_dict_path(explicit=None) -> Path:
    if explicit:
        return Path(explicit)
    if DEFAULT_JSON_FIELD_DICT.exists():
        return DEFAULT_JSON_FIELD_DICT
    return LEGACY_JSON_FIELD_DICT
