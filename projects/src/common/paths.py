"""Project paths shared by discovery and greedy workflows."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent
WORKSPACE_ROOT = REPO_ROOT.parent

VALID_ENCODINGS = ("prompt", "onehot")

DEFAULT_JSON_PATH = (
    str(PROJECT_ROOT / "ClinicDatasets" / "gdc_clinical" / "raw_json" / "TCGA-BRCA.json")
)
DEFAULT_DATASETS_CONFIG = str(PROJECT_ROOT / "datasets.json")
DEFAULT_CKPT = str(WORKSPACE_ROOT / "CONCH/pytorch_model.bin")
DEFAULT_JSON_FIELD_DICT = PROJECT_ROOT / "templates" / "field_labels.json"
LEGACY_JSON_FIELD_DICT = PROJECT_ROOT / "templates" / "common" / "json_field_dictionary.json"
RAWDATA_STATS_ROOT = PROJECT_ROOT / "rawdata_stats"
RAWDATA_STATS_SHARED_DIR = RAWDATA_STATS_ROOT / "_shared"
DEFAULT_GDC_CASES_MAPPING = (
    PROJECT_ROOT / "ClinicDatasets" / "gdc_clinical" / "field_tables" / "gdc_cases_mapping.csv"
)
REGISTRY_DIR = RAWDATA_STATS_SHARED_DIR
REGISTRY_DICTS_DIR = RAWDATA_STATS_ROOT
TIME_STATS_ROOT = RAWDATA_STATS_ROOT

DEFAULT_GPU = "7"


def validate_encoding(encoding: str) -> str:
    value = str(encoding or "").strip().lower()
    if value not in VALID_ENCODINGS:
        allowed = ", ".join(VALID_ENCODINGS)
        raise ValueError(f"unsupported encoding {encoding!r}; expected one of: {allowed}")
    return value


def dataset_stats_dir(dataset_name: str) -> Path:
    return RAWDATA_STATS_ROOT / dataset_name


def dataset_field_bank_template_dir(dataset_name: str) -> Path:
    return PROJECT_ROOT / "templates" / "field_bank" / dataset_name


def dataset_field_bank_dir(dataset_name: str, encoding: str = "prompt") -> Path:
    encoding = validate_encoding(encoding)
    return PROJECT_ROOT / "outputs" / dataset_name / "field_bank" / encoding


def dataset_greedy_dir(dataset_name: str, encoding: str = "prompt") -> Path:
    encoding = validate_encoding(encoding)
    return PROJECT_ROOT / "outputs" / dataset_name / "greedy" / encoding


def dataset_field_dict_path(dataset_name: str) -> Path:
    return RAWDATA_STATS_ROOT / dataset_name / "scanned_fields.json"


def dataset_field_presence_path(dataset_name: str) -> Path:
    return RAWDATA_STATS_ROOT / dataset_name / "field_presence.csv"


def dataset_field_presence_summary_path(dataset_name: str) -> Path:
    return RAWDATA_STATS_ROOT / dataset_name / "field_presence_summary.json"


def shared_field_presence_path() -> Path:
    return RAWDATA_STATS_SHARED_DIR / "field_presence.csv"


def shared_field_presence_summary_path() -> Path:
    return RAWDATA_STATS_SHARED_DIR / "field_presence_summary.csv"


def shared_field_presence_mapping_census_path() -> Path:
    return RAWDATA_STATS_SHARED_DIR / "field_presence_mapping_census.csv"


def shared_field_presence_not_in_table_path() -> Path:
    return RAWDATA_STATS_SHARED_DIR / "field_presence_not_in_table.csv"


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


def resolve_reference_dict_path(explicit=None) -> Path:
    if explicit:
        return Path(explicit)
    if DEFAULT_JSON_FIELD_DICT.exists():
        return DEFAULT_JSON_FIELD_DICT
    return LEGACY_JSON_FIELD_DICT
