"""Project paths shared by discovery and greedy workflows."""

from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent
WORKSPACE_ROOT = REPO_ROOT.parent

VALID_ENCODINGS = ("prompt", "onehot")
VALID_SCHEMES = ("L2", "L3", "L5")
DEFAULT_L5_GROUPS_CSV = PROJECT_ROOT / "templates" / "field_bank" / "_shared" / "l5_semantic_groups.csv"
LANDMARK_OFF_TAG = "landmark_none"
_LANDMARK_TAG_RE = re.compile(rf"^(?:{LANDMARK_OFF_TAG}|landmark_(\d+))$")
_SCHEME_RUN_TAG_RE = re.compile(
    rf"^(?:{LANDMARK_OFF_TAG}|landmark_(\d+))_({'|'.join(VALID_SCHEMES)})$"
)
LONGITUDINAL_EXPERIMENT = "longitudinal"
VALID_EXPERIMENTS = ("", LONGITUDINAL_EXPERIMENT)
RESULT_EXPERIMENTS = (
    "greedy",
    "univariate",
    "linear_probe",
    "longitudinal_greedy",
    "longitudinal_univariate",
    "schemes",
)

DEFAULT_JSON_PATH = (
    str(PROJECT_ROOT / "ClinicDatasets" / "gdc_clinical" / "raw_json" / "TCGA-BRCA.json")
)
DEFAULT_DATASETS_CONFIG = str(PROJECT_ROOT / "datasets.json")
DEFAULT_CKPT = str(WORKSPACE_ROOT / "CONCH/pytorch_model.bin")
DEFAULT_JSON_FIELD_DICT = PROJECT_ROOT / "templates" / "field_labels.json"
DEFAULT_FIELD_FILTER_RULES = PROJECT_ROOT / "templates" / "field_filter_rules.json"
LEGACY_JSON_FIELD_DICT = PROJECT_ROOT / "templates" / "common" / "json_field_dictionary.json"
RAWDATA_STATS_ROOT = PROJECT_ROOT / "rawdata_stats"
RAWDATA_STATS_SHARED_DIR = RAWDATA_STATS_ROOT / "_shared"
RESULTS_ROOT = PROJECT_ROOT / "results"
RESULTS_DISPLAY_ROOT = PROJECT_ROOT / "results_display"
DEFAULT_GDC_CASES_MAPPING = (
    PROJECT_ROOT / "ClinicDatasets" / "gdc_clinical" / "field_tables" / "gdc_cases_mapping.csv"
)
DEFAULT_GDC_CLINICAL_DICTIONARY = (
    PROJECT_ROOT / "ClinicDatasets" / "gdc_clinical" / "field_tables" / "gdc_clinical_dictionary.csv"
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


def validate_scheme(scheme: str) -> str:
    value = str(scheme or "").strip()
    if value not in VALID_SCHEMES:
        allowed = ", ".join(VALID_SCHEMES)
        raise ValueError(f"unsupported scheme {scheme!r}; expected one of: {allowed}")
    return value


def parse_landmark_time_value(raw):
    if raw is None or raw == "":
        raise ValueError("必须传入 --landmark_time，例如 --landmark_time 365 或 --landmark_time none")
    if isinstance(raw, str):
        value = raw.strip().lower()
        if value in {"none", "off", "false"}:
            return None
        raw = value
    if raw is False:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("--landmark_time 必须是非负整数天，或 none") from exc
    if value < 0 or not value.is_integer():
        raise ValueError("--landmark_time 必须是非负整数天，或 none")
    return int(value)


def split_csv_tokens(raw) -> list[str]:
    if raw is None or raw is False:
        return []
    if isinstance(raw, (list, tuple, set)):
        tokens = []
        for item in raw:
            tokens.extend(split_csv_tokens(item))
        return tokens
    text = str(raw).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def landmark_token_from_tag(tag: str) -> str:
    value = require_landmark_tag(tag)
    if value == LANDMARK_OFF_TAG:
        return "none"
    return value.rsplit("_", 1)[1]


def landmark_sort_key(tag_or_token: str):
    raw = str(tag_or_token or "").strip()
    if raw in {LANDMARK_OFF_TAG, "none", "off", "false"}:
        return (1, 0)
    if raw.startswith("landmark_"):
        raw = raw.rsplit("_", 1)[1]
    try:
        return (0, int(raw))
    except (TypeError, ValueError):
        return (2, raw)


def iter_landmark_tags(parent: Path | str | None) -> list[str]:
    root = Path(parent) if parent is not None else None
    if root is None or not root.is_dir():
        return []
    tags = {
        child.name
        for child in root.iterdir()
        if child.is_dir() and _LANDMARK_TAG_RE.fullmatch(child.name)
    }
    return sorted(tags, key=landmark_sort_key)


def parse_landmark_time_list(raw) -> list[str]:
    tokens = split_csv_tokens(raw)
    if not tokens:
        raise ValueError("必须传入 --landmark_time，例如 --landmark_time 365、--landmark_time none,365 或 --landmark_time all")
    lowered = [token.lower() for token in tokens]
    if "all" in lowered:
        if len(tokens) != 1:
            raise ValueError("--landmark_time all 不能和具体天数混用")
        return ["all"]
    out = []
    seen = set()
    for token in tokens:
        parsed = parse_landmark_time_value(token)
        canonical = "none" if parsed is None else str(int(parsed))
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
    return out


def canonical_landmark_spec(raw) -> str:
    tokens = parse_landmark_time_list(raw)
    if tokens == ["all"]:
        return "all"
    return ",".join(sorted(tokens, key=landmark_sort_key))


def resolve_landmark_time_tokens(
    raw,
    *,
    scan_roots=None,
    context: str | None = None,
) -> list[str]:
    tokens = parse_landmark_time_list(raw)
    if tokens != ["all"]:
        return tokens
    if scan_roots is None:
        roots: list[Path] = []
    elif isinstance(scan_roots, (str, Path)):
        roots = [Path(scan_roots)]
    else:
        roots = [Path(path) for path in scan_roots]
    tags: list[str] = []
    seen: set[str] = set()
    for root in roots:
        for tag in iter_landmark_tags(root):
            if tag in seen:
                continue
            seen.add(tag)
            tags.append(tag)
    tags = sorted(tags, key=landmark_sort_key)
    if not tags:
        scanned = ", ".join(str(path) for path in roots) or "(none)"
        prefix = f"{context}: " if context else ""
        raise ValueError(f"{prefix}--landmark_time all 未找到 landmark_* 目录，已扫描: {scanned}")
    return [landmark_token_from_tag(tag) for tag in tags]


def coerce_landmark_days(landmark_time) -> int:
    parsed = parse_landmark_time_value(landmark_time)
    if parsed is None:
        raise ValueError("开启 landmark 时必须传入 --landmark_time 天数，不能是 none")
    return parsed


def landmark_tag(*, no_landmark: bool = False, landmark_time=None) -> str:
    if bool(no_landmark):
        if landmark_time not in (None, "", False):
            if isinstance(landmark_time, str) and landmark_time.strip().lower() in {"none", "off", "false"}:
                return LANDMARK_OFF_TAG
            raise ValueError("关闭 landmark 时 --landmark_time 只能是 none")
        return LANDMARK_OFF_TAG
    parsed = parse_landmark_time_value(landmark_time)
    if parsed is None:
        return LANDMARK_OFF_TAG
    return f"landmark_{parsed}"


def landmark_tag_from_args(args) -> str:
    return landmark_tag(landmark_time=getattr(args, "landmark_time", None))


def require_landmark_tag(tag: str | None) -> str:
    value = str(tag or "").strip()
    if not _LANDMARK_TAG_RE.fullmatch(value):
        raise ValueError(
            f"unsupported landmark_tag {tag!r}; expected {LANDMARK_OFF_TAG} or landmark_{{N}}"
        )
    return value


def normalize_experiment(experiment: str | None = None) -> str:
    value = str(experiment or "").strip().lower()
    if value in {"", "default", "standard", "main"}:
        return ""
    if value == LONGITUDINAL_EXPERIMENT:
        return LONGITUDINAL_EXPERIMENT
    raise ValueError(
        f"unsupported experiment {experiment!r}; expected empty or {LONGITUDINAL_EXPERIMENT}"
    )


def normalize_result_experiment(experiment: str | None = None) -> str:
    value = str(experiment or "").strip().lower()
    if value in RESULT_EXPERIMENTS:
        return value
    raise ValueError(
        f"unsupported result experiment {experiment!r}; expected one of: {', '.join(RESULT_EXPERIMENTS)}"
    )


def result_experiment_name(kind: str, experiment: str | None = None) -> str:
    kind_value = str(kind or "").strip().lower()
    if kind_value not in {"greedy", "univariate", "linear_probe", "schemes"}:
        raise ValueError(f"unsupported result kind {kind!r}")
    encoding_experiment = normalize_experiment(experiment)
    if encoding_experiment == LONGITUDINAL_EXPERIMENT:
        if kind_value in {"greedy", "univariate"}:
            return f"longitudinal_{kind_value}"
        raise ValueError(f"{kind_value} has no longitudinal results tree")
    return kind_value


def experiment_path_parts(experiment: str | None = None) -> tuple[str, ...]:
    value = normalize_experiment(experiment)
    return (value,) if value else ()


def experiment_from_args(args, default: str | None = None) -> str:
    return normalize_experiment(getattr(args, "experiment", default))


def experiment_from_path(path: Path | str) -> str:
    if LONGITUDINAL_EXPERIMENT in Path(path).parts:
        return LONGITUDINAL_EXPERIMENT
    return ""


def encoding_and_landmark_tag_from_path(path: Path | str) -> tuple[str | None, str | None]:
    parts = Path(path).parts
    for idx, part in enumerate(parts):
        if part not in VALID_ENCODINGS:
            continue
        tag = None
        if idx + 1 < len(parts) and parts[idx + 1] not in {"embeddings", "subsets", "pt"}:
            nxt = parts[idx + 1]
            if _LANDMARK_TAG_RE.fullmatch(nxt):
                tag = nxt
        return part, tag
    return None, None


def dataset_stats_dir(dataset_name: str) -> Path:
    return RAWDATA_STATS_ROOT / dataset_name


def dataset_field_bank_template_dir(dataset_name: str, landmark_tag: str | None = None) -> Path:
    tag = require_landmark_tag(landmark_tag)
    return PROJECT_ROOT / "templates" / "field_bank" / dataset_name / tag


def dataset_outputs_root(dataset_name: str, experiment: str | None = None) -> Path:
    root = PROJECT_ROOT / "outputs" / dataset_name
    for part in experiment_path_parts(experiment):
        root = root / part
    return root


def dataset_field_bank_dir(
    dataset_name: str,
    encoding: str = "prompt",
    landmark_tag: str | None = None,
    experiment: str | None = None,
) -> Path:
    encoding = validate_encoding(encoding)
    tag = require_landmark_tag(landmark_tag)
    return dataset_outputs_root(dataset_name, experiment) / "field_bank" / encoding / tag


def dataset_greedy_dir(
    dataset_name: str,
    encoding: str = "prompt",
    landmark_tag: str | None = None,
    experiment: str | None = None,
) -> Path:
    encoding = validate_encoding(encoding)
    tag = require_landmark_tag(landmark_tag)
    return dataset_outputs_root(dataset_name, experiment) / "greedy" / encoding / tag


def dataset_univariate_dir(
    dataset_name: str,
    encoding: str = "prompt",
    landmark_tag: str | None = None,
    experiment: str | None = None,
) -> Path:
    encoding = validate_encoding(encoding)
    tag = require_landmark_tag(landmark_tag)
    return dataset_outputs_root(dataset_name, experiment) / "univariate" / encoding / tag


def dataset_linear_probe_dir(
    dataset_name: str,
    encoding: str = "prompt",
    landmark_tag: str | None = None,
    experiment: str | None = None,
) -> Path:
    encoding = validate_encoding(encoding)
    tag = require_landmark_tag(landmark_tag)
    return dataset_outputs_root(dataset_name, experiment) / "linear_probe" / encoding / tag


def dataset_results_dir(
    experiment: str,
    encoding: str,
    landmark_tag: str | None,
    dataset_name: str,
) -> Path:
    experiment_name = normalize_result_experiment(experiment)
    encoding_value = validate_encoding(encoding)
    tag = require_landmark_tag(landmark_tag)
    return RESULTS_ROOT / experiment_name / encoding_value / tag / dataset_name


def dataset_greedy_results_dir(
    dataset_name: str,
    encoding: str = "prompt",
    landmark_tag: str | None = None,
    experiment: str | None = None,
) -> Path:
    return dataset_results_dir(
        result_experiment_name("greedy", experiment),
        encoding,
        landmark_tag,
        dataset_name,
    )


def dataset_univariate_results_dir(
    dataset_name: str,
    encoding: str = "prompt",
    landmark_tag: str | None = None,
    experiment: str | None = None,
) -> Path:
    return dataset_results_dir(
        result_experiment_name("univariate", experiment),
        encoding,
        landmark_tag,
        dataset_name,
    )


def dataset_linear_probe_results_dir(
    dataset_name: str,
    encoding: str = "prompt",
    landmark_tag: str | None = None,
    experiment: str | None = None,
) -> Path:
    if normalize_experiment(experiment):
        raise ValueError("linear_probe has no longitudinal results tree")
    return dataset_results_dir("linear_probe", encoding, landmark_tag, dataset_name)


def display_results_dir(
    experiment: str,
    encoding: str,
    landmark_tag: str | None = None,
) -> Path:
    experiment_name = normalize_result_experiment(experiment)
    encoding_value = validate_encoding(encoding)
    tag = require_landmark_tag(landmark_tag)
    return RESULTS_DISPLAY_ROOT / experiment_name / encoding_value / tag


def scheme_run_tag(landmark_tag: str, scheme: str) -> str:
    tag = require_landmark_tag(landmark_tag)
    scheme = validate_scheme(scheme)
    return f"{tag}_{scheme}"


def parse_scheme_run_tag(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not _SCHEME_RUN_TAG_RE.fullmatch(raw):
        raise ValueError(
            f"unsupported scheme run tag {value!r}; expected {LANDMARK_OFF_TAG}_L2/L3/L5 or landmark_{{N}}_L2/L3/L5"
        )
    landmark_tag, scheme = raw.rsplit("_", 1)
    return require_landmark_tag(landmark_tag), validate_scheme(scheme)


def dataset_scheme_dir(
    dataset_name: str,
    scheme: str,
    landmark_tag: str | None = None,
    experiment: str | None = None,
) -> Path:
    scheme = validate_scheme(scheme)
    tag = require_landmark_tag(landmark_tag)
    return dataset_outputs_root(dataset_name, experiment) / "schemes" / scheme_run_tag(tag, scheme)


def shared_l5_groups_path() -> Path:
    return DEFAULT_L5_GROUPS_CSV


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


def dataset_kept_fields_path(dataset_name: str, landmark_tag: str | None = None) -> Path:
    tag = require_landmark_tag(landmark_tag)
    return RAWDATA_STATS_ROOT / dataset_name / tag / "kept_fields.json"


def shared_kept_fields_path(landmark_tag: str | None = None) -> Path:
    tag = require_landmark_tag(landmark_tag)
    return RAWDATA_STATS_SHARED_DIR / tag / "kept_fields.json"


def shared_field_stats_path() -> Path:
    return RAWDATA_STATS_SHARED_DIR / "field_stats.csv"


def dataset_filter_log_dir(dataset_name: str, landmark_tag: str | None = None) -> Path:
    tag = require_landmark_tag(landmark_tag)
    return RAWDATA_STATS_ROOT / dataset_name / tag / "fliter_log"


def dataset_exclusion_log_path(dataset_name: str, landmark_tag: str | None = None) -> Path:
    return dataset_filter_log_dir(dataset_name, landmark_tag) / "exclusion_log.csv"


def dataset_field_registry_path(dataset_name: str, landmark_tag: str | None = None) -> Path:
    return dataset_filter_log_dir(dataset_name, landmark_tag) / "field_registry.csv"


def resolve_reference_dict_path(explicit=None) -> Path:
    if explicit:
        return Path(explicit)
    if DEFAULT_GDC_CLINICAL_DICTIONARY.exists():
        return DEFAULT_GDC_CLINICAL_DICTIONARY
    if DEFAULT_JSON_FIELD_DICT.exists():
        return DEFAULT_JSON_FIELD_DICT
    return LEGACY_JSON_FIELD_DICT
