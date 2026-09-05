"""Encode D0-D5 and paper-scheme mixed baseline vectors from clinical JSON."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import re

import numpy as np

from common.clinical_io import load_clinical_cases, normalize_json_paths
from common.fields import DERIVED_FIELD_TYPES, HUMAN_SCHEME_FIELDS, field_gdc_path
from common.missingness import is_missing_token
from discovery.onehot import (
    _load_gdc_dictionary,
    classify_gdc_types,
    gdc_lookup_key,
    parse_gdc_types,
)
from .extract import extract_values
from .paths import global_mapping_dir as shared_global_mapping_dir


BASELINE_ENCODING_NAME = "onehot_ordinary"
BASELINE_MISSING_TOKEN = "__MISSING__"
BASELINE_OTHER_TOKEN = "__OTHER__"

BASELINE_CONTINUOUS_FIELDS = {
    "demographic.age_at_index",
    "diagnoses[].year_of_diagnosis",
    "diagnoses[].age_at_diagnosis",
    "diagnoses[].pathology_details[].lymph_nodes_tested",
    "diagnoses[].pathology_details[].lymph_nodes_positive",
    "follow_ups[].other_clinical_attributes[].bmi",
}

BASELINE_ORDINAL_FIELDS = {
    "diagnoses[].tumor_grade",
    "diagnoses[].ajcc_pathologic_t",
    "diagnoses[].ajcc_pathologic_n",
    "diagnoses[].ajcc_pathologic_m",
    "diagnoses[].ajcc_pathologic_stage",
    "follow_ups[].ecog_performance_status",
}

BASELINE_NOMINAL_FIELDS = {
    "demographic.sex_at_birth",
    "demographic.race",
    "demographic.ethnicity",
    "diagnoses[].primary_diagnosis",
    "diagnoses[].morphology",
    "diagnoses[].tissue_or_organ_of_origin",
    "diagnoses[].laterality",
    "diagnoses[].prior_malignancy",
    "diagnoses[].synchronous_malignancy",
    "diagnoses[].prior_treatment",
    "diagnoses[].ajcc_staging_system_edition",
}

DEFAULT_BASELINE_SCHEMES = ["D0", "D1", "D2", "D3", "D4", "D5"]
PAPER_BASELINE_SCHEMES = [
    "MULTISURV",
    "SURVPGC",
    "MMSURV",
    "INTEGRATIVE_DNN",
    "HGCN_KIRC",
    "HGCN_LIHC",
    "HGCN_ESCA",
    "HGCN_LUSC",
    "HGCN_LUAD",
    "HGCN_UCEC",
]
D_SCHEME_BY_TEXT_SCHEME = {
    "L0": "D0",
    "L1": "D1",
    "L2": "D2",
    "L3": "D3",
    "L4": "D4",
    "L5": "D5",
}

# project.project_id is not in the GDC dictionary dump used here.
PAPER_FIELD_TYPES = {
    "project.project_id": "nominal",
    **DERIVED_FIELD_TYPES,
}

BASELINE_SCHEME_FIELDS = {}


def load_baseline_scheme_fields(text_scheme_fields: dict[str, list[str]]) -> None:
    BASELINE_SCHEME_FIELDS.clear()
    for text_scheme, d_scheme in D_SCHEME_BY_TEXT_SCHEME.items():
        if text_scheme not in text_scheme_fields:
            raise ValueError(f"缺少文本方案 {text_scheme}，无法派生 {d_scheme}")
        BASELINE_SCHEME_FIELDS[d_scheme] = list(text_scheme_fields[text_scheme])
    for name in PAPER_BASELINE_SCHEMES:
        if name not in text_scheme_fields:
            raise ValueError(f"缺少论文方案 {name}，无法注册 baseline 字段")
        BASELINE_SCHEME_FIELDS[name] = list(text_scheme_fields[name])


BASELINE_EXTRA_MISSING = {"stage x", "tx", "nx", "mx"}

# Frozen HGCN field-type sets above. D-group vectors use dictionary types below.


def _classify_field(field: str, dictionary: dict[tuple[str, str], str]) -> str:
    if field in PAPER_FIELD_TYPES:
        return PAPER_FIELD_TYPES[field]
    field_path = field_gdc_path(field)
    gdc_type = dictionary.get(gdc_lookup_key(field_path), "")
    classified = classify_gdc_types(parse_gdc_types(gdc_type))
    if classified is None:
        raise ValueError(
            f"GDC dictionary 无法分类人工方案字段 {field} ({field_path}): type={gdc_type!r}"
        )
    return classified


def _load_dictionary_field_types() -> dict[str, str]:
    dictionary = _load_gdc_dictionary()
    return {
        field: _classify_field(field, dictionary)
        for field in HUMAN_SCHEME_FIELDS
    }


BASELINE_DICTIONARY_FIELD_TYPES = _load_dictionary_field_types()
BASELINE_ORDINARY_FIELDS = {
    field for field, kind in BASELINE_DICTIONARY_FIELD_TYPES.items() if kind == "continuous"
}
BASELINE_ONEHOT_FIELDS = {
    field for field, kind in BASELINE_DICTIONARY_FIELD_TYPES.items() if kind == "nominal"
}


def resolve_baseline_schemes(scheme: str) -> list[str]:
    known = list(BASELINE_SCHEME_FIELDS.keys())
    if scheme == "all":
        return list(DEFAULT_BASELINE_SCHEMES)
    if scheme not in BASELINE_SCHEME_FIELDS:
        raise ValueError(f"未知 baseline 方案: '{scheme}'。可用方案: {sorted(known)}")
    return [scheme]


def baseline_scheme_output_dir(out_root: str | Path, scheme: str) -> Path:
    root = Path(out_root)
    if scheme in DEFAULT_BASELINE_SCHEMES:
        return root / scheme
    return root / "baseline" / scheme



def baseline_field_encoding(field: str) -> str:
    if field in BASELINE_ORDINARY_FIELDS:
        return "ordinary"
    if field in BASELINE_ONEHOT_FIELDS:
        return "onehot"
    raise KeyError(f"未知 baseline 字段: {field}")


def _split_collapsed_values(raw_value) -> list[str]:
    if raw_value is None:
        return []
    text = str(raw_value).strip()
    if not text:
        return []
    return [x.strip() for x in text.split(",") if str(x).strip()]


def _is_missing_baseline_token(token: str) -> bool:
    return is_missing_token(token, extra=BASELINE_EXTRA_MISSING)


def _canonical_nominal_value(raw_value) -> str:
    tokens = []
    for token in _split_collapsed_values(raw_value):
        cleaned = " ".join(str(token).strip().lower().split())
        if not _is_missing_baseline_token(cleaned):
            tokens.append(cleaned)
    uniq = sorted(set(tokens))
    return " | ".join(uniq) if uniq else BASELINE_MISSING_TOKEN


def _extract_numeric_values(raw_value) -> list[float]:
    nums = []
    for token in _split_collapsed_values(raw_value):
        cleaned = token.strip()
        if _is_missing_baseline_token(cleaned):
            continue
        match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
        if match:
            nums.append(float(match.group(0)))
    return nums


def _aggregate_continuous_value(field: str, raw_value) -> float | None:
    nums = _extract_numeric_values(raw_value)
    if not nums:
        return None
    if field == "diagnoses[].age_at_diagnosis":
        nums = [x / 365.25 if x > 365 else x for x in nums]
    return float(np.median(nums))


def _fit_continuous_stats(patient_rows: list[dict]) -> dict:
    stats = {}
    for field in sorted(BASELINE_ORDINARY_FIELDS):
        vals = [
            v for v in (_aggregate_continuous_value(field, row.get(field)) for row in patient_rows)
            if v is not None
        ]
        if vals:
            stats[field] = {
                "median": float(np.median(vals)),
                "min": float(np.min(vals)),
                "max": float(np.max(vals)),
            }
        else:
            stats[field] = {"median": 0.0, "min": 0.0, "max": 0.0}
    return stats


def _normalize_continuous_value(field: str, raw_value, stats: dict) -> float:
    field_stats = stats[field]
    value = _aggregate_continuous_value(field, raw_value)
    if value is None:
        value = float(field_stats["median"])
    vmin = float(field_stats["min"])
    vmax = float(field_stats["max"])
    if vmax <= vmin:
        return 0.0
    return float((value - vmin) / (vmax - vmin))


def _encode_tumor_grade(token: str) -> int:
    compact = token.lower().replace(" ", "")
    match = re.search(r"g([1-4])", compact)
    return int(match.group(1)) if match else 0


def _encode_t_stage(token: str) -> int:
    compact = token.lower().replace(" ", "")
    match = re.search(r"t(is|[0-4])", compact)
    if not match:
        return 0
    stage = match.group(1)
    if stage == "is":
        return 1
    return int(stage) + 2


def _encode_n_stage(token: str) -> int:
    compact = token.lower().replace(" ", "")
    match = re.search(r"n([0-3])", compact)
    return int(match.group(1)) + 1 if match else 0


def _encode_m_stage(token: str) -> int:
    compact = token.lower().replace(" ", "")
    match = re.search(r"m([0-1])", compact)
    return int(match.group(1)) + 1 if match else 0


def _encode_overall_stage(token: str) -> int:
    compact = token.lower().replace(" ", "")
    compact = compact.replace("stage", "")
    if not compact:
        return 0
    if compact.startswith("iv"):
        return 5
    if compact.startswith("iii"):
        return 4
    if compact.startswith("ii"):
        return 3
    if compact.startswith("i"):
        return 2
    if compact.startswith("0"):
        return 1
    return 0


def _encode_ecog(token: str) -> int:
    compact = token.lower().replace(" ", "")
    match = re.search(r"([0-5])", compact)
    return int(match.group(1)) + 1 if match else 0


def _encode_ordinal_value(field: str, raw_value) -> int:
    encoders = {
        "diagnoses[].tumor_grade": _encode_tumor_grade,
        "diagnoses[].ajcc_pathologic_t": _encode_t_stage,
        "diagnoses[].ajcc_pathologic_n": _encode_n_stage,
        "diagnoses[].ajcc_pathologic_m": _encode_m_stage,
        "diagnoses[].ajcc_pathologic_stage": _encode_overall_stage,
        "follow_ups[].ecog_performance_status": _encode_ecog,
    }
    encoder = encoders[field]
    codes = []
    for token in _split_collapsed_values(raw_value):
        if _is_missing_baseline_token(token):
            continue
        code = encoder(token)
        if code > 0:
            codes.append(code)
    return max(codes) if codes else 0


def _count_categories(patient_rows: list[dict], fields: set[str] | list[str]) -> dict[str, Counter]:
    counts = {}
    for field in sorted(fields):
        counter = Counter()
        for row in patient_rows:
            value = _canonical_nominal_value(row.get(field))
            if value != BASELINE_MISSING_TOKEN:
                counter[value] += 1
        counts[field] = counter
    return counts


def _fit_category_mappings(
    patient_rows: list[dict],
    fields: set[str] | list[str],
    *,
    min_count: int = 1,
    collapse_rare: bool = False,
) -> dict:
    mappings = {}
    counts = _count_categories(patient_rows, fields)
    for field in sorted(fields):
        if collapse_rare:
            categories = sorted(
                category
                for category, count in counts[field].items()
                if count >= min_count
            )
        else:
            categories = sorted(counts[field])
        mapping = {
            BASELINE_MISSING_TOKEN: 0,
            BASELINE_OTHER_TOKEN: 1,
        }
        for category in categories:
            mapping[category] = len(mapping)
        mappings[field] = mapping
    return mappings


def fit_nominal_mappings(
    patient_rows: list[dict],
    *,
    min_count: int = 1,
    collapse_rare: bool = False,
) -> dict:
    """HGCN-facing helper: only the frozen nominal field set."""
    return _fit_category_mappings(
        patient_rows,
        BASELINE_NOMINAL_FIELDS,
        min_count=min_count,
        collapse_rare=collapse_rare,
    )


def fit_onehot_mappings(
    patient_rows: list[dict],
    *,
    min_count: int = 1,
    collapse_rare: bool = False,
) -> dict:
    """D-group helper: dictionary enum/boolean fields."""
    return _fit_category_mappings(
        patient_rows,
        BASELINE_ONEHOT_FIELDS,
        min_count=min_count,
        collapse_rare=collapse_rare,
    )


def _encode_nominal_value(field: str, raw_value, mappings: dict) -> int:
    mapping = mappings[field]
    value = _canonical_nominal_value(raw_value)
    if value == BASELINE_MISSING_TOKEN:
        return mapping[BASELINE_MISSING_TOKEN]
    return mapping.get(value, mapping[BASELINE_OTHER_TOKEN])


def _build_baseline_vector(
    row: dict,
    fields: list[str],
    continuous_stats: dict,
    nominal_mappings: dict,
) -> np.ndarray:
    vec = []
    for field in fields:
        encoding = baseline_field_encoding(field)
        if encoding == "ordinary":
            vec.append(_normalize_continuous_value(field, row.get(field), continuous_stats))
        elif encoding == "onehot":
            code = _encode_nominal_value(field, row.get(field), nominal_mappings)
            onehot = np.zeros(len(nominal_mappings[field]), dtype=np.float32)
            onehot[code] = 1.0
            vec.extend(onehot.tolist())
        else:
            raise KeyError(f"未知 baseline 字段: {field}")
    return np.asarray(vec, dtype=np.float32)


def build_baseline_feature_schema(nominal_mappings: dict) -> dict:
    schemas = {}
    for scheme, fields in BASELINE_SCHEME_FIELDS.items():
        cursor = 0
        features = []
        for field in fields:
            encoding = baseline_field_encoding(field)
            dim = len(nominal_mappings[field]) if encoding == "onehot" else 1
            feature = {
                "field": field,
                "field_type": encoding,
                "start": cursor,
                "dim": dim,
            }
            if encoding == "onehot":
                feature["categories"] = [
                    key for key, _ in sorted(nominal_mappings[field].items(), key=lambda kv: kv[1])
                ]
            features.append(feature)
            cursor += dim
        schemas[scheme] = {
            "output_dim": cursor,
            "features": features,
        }
    return schemas


def save_baseline_metadata(
    metadata_dir: Path,
    encoding: str,
    continuous_stats: dict,
    nominal_mappings: dict,
    feature_schema: dict,
    nominal_min_count: int | None = None,
    mapping_scope: dict | None = None,
    save_nominal_mapping: bool = True,
    save_feature_schema: bool = True,
    global_metadata_dir: Path | None = None,
) -> None:
    metadata_dir.mkdir(parents=True, exist_ok=True)

    normalization_stats = {
        "encoding": encoding,
        "continuous_method": "minmax",
        "fields": continuous_stats,
    }
    category_mapping = {
        "encoding": encoding,
        "missing_token": BASELINE_MISSING_TOKEN,
        "other_token": BASELINE_OTHER_TOKEN,
        "nominal_min_count": nominal_min_count,
        "mapping_scope": mapping_scope,
        "fields": nominal_mappings,
    }
    schema_payload = {
        "encoding": encoding,
        "schemes": feature_schema,
    }

    with open(metadata_dir / "normalization_stats.json", "w", encoding="utf-8") as f:
        json.dump(normalization_stats, f, ensure_ascii=False, indent=2)
    if save_nominal_mapping:
        with open(metadata_dir / "category_mapping.json", "w", encoding="utf-8") as f:
            json.dump(category_mapping, f, ensure_ascii=False, indent=2)
    if save_feature_schema:
        with open(metadata_dir / "feature_schema.json", "w", encoding="utf-8") as f:
            json.dump(schema_payload, f, ensure_ascii=False, indent=2)
    if global_metadata_dir is not None:
        ref_payload = {
            "encoding": encoding,
            "global_metadata_dir": str(global_metadata_dir),
            "category_mapping_json": str(global_metadata_dir / "category_mapping.json"),
            "feature_schema_json": str(global_metadata_dir / "feature_schema.json"),
        }
        with open(metadata_dir / "global_metadata_ref.json", "w", encoding="utf-8") as f:
            json.dump(ref_payload, f, ensure_ascii=False, indent=2)


def save_global_baseline_metadata(
    metadata_dir: Path,
    nominal_mappings: dict,
    feature_schema: dict,
    nominal_min_count: int,
    dataset_names: list[str],
    patient_count: int,
) -> None:
    metadata_dir.mkdir(parents=True, exist_ok=True)
    category_mapping = {
        "encoding": BASELINE_ENCODING_NAME,
        "missing_token": BASELINE_MISSING_TOKEN,
        "other_token": BASELINE_OTHER_TOKEN,
        "nominal_min_count": nominal_min_count,
        "mapping_scope": {
            "type": "global_selected_datasets",
            "datasets": dataset_names,
            "patient_count": patient_count,
        },
        "fields": nominal_mappings,
    }
    schema_payload = {
        "encoding": BASELINE_ENCODING_NAME,
        "schemes": feature_schema,
    }
    with open(metadata_dir / "category_mapping.json", "w", encoding="utf-8") as f:
        json.dump(category_mapping, f, ensure_ascii=False, indent=2)
    with open(metadata_dir / "feature_schema.json", "w", encoding="utf-8") as f:
        json.dump(schema_payload, f, ensure_ascii=False, indent=2)


def load_baseline_metadata(metadata_dir: str) -> tuple[dict, dict]:
    meta = Path(metadata_dir)
    stats_path = meta / "normalization_stats.json"
    mapping_path = meta / "category_mapping.json"
    if not stats_path.exists():
        raise FileNotFoundError(f"baseline metadata 缺少 {stats_path.name}: {meta}")
    if not mapping_path.exists():
        ref_path = meta / "global_metadata_ref.json"
        if ref_path.exists():
            with open(ref_path, "r", encoding="utf-8") as f:
                ref_payload = json.load(f)
            mapping_path = Path(ref_payload["category_mapping_json"])
        else:
            raise FileNotFoundError(
                f"baseline metadata 不完整: 需要 {stats_path.name} 和 {mapping_path.name}，当前目录 {meta}"
            )
    with open(stats_path, "r", encoding="utf-8") as f:
        stats_payload = json.load(f)
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping_payload = json.load(f)
    return dict(stats_payload["fields"]), dict(mapping_payload["fields"])


def build_patient_rows(cases: list[dict]) -> list[dict]:
    rows = []
    for case in cases:
        row = {"patient_id": str(case["submitter_id"]).strip()}
        row.update(extract_values(case))
        rows.append(row)
    return rows


def run_baseline_encode(
    json_paths,
    schemes: list[str],
    out_root: str,
    project_ids: list | None = None,
    stats_dir: str | None = None,
    nominal_min_count: int = 5,
    shared_nominal_mappings: dict | None = None,
    mapping_scope: dict | None = None,
    global_metadata_dir: str | None = None,
):
    try:
        import torch
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "baseline 输出为 .pt 文件，当前 Python 环境缺少 torch。请切换到包含 torch 的环境后重试。"
        ) from exc

    print(f"\n{'='*55}")
    print(f"[baseline] 编码方式 {BASELINE_ENCODING_NAME}")
    print(f"  JSON     : {normalize_json_paths(json_paths)}")
    print(f"  输出根目录 : {out_root}")
    if stats_dir:
        print(f"  复用统计量 : {stats_dir}")
    else:
        print("  复用统计量 : 否（当前运行数据拟合）")
    print(f"  onehot 阈值: >= {nominal_min_count} 保留，否则合并到 {BASELINE_OTHER_TOKEN}")
    print(f"{'='*55}")

    print("\n[1/3] 读取 JSON ...")
    cases = load_clinical_cases(json_paths, project_ids=project_ids)
    patient_rows = build_patient_rows(cases)
    print(f"      患者数: {len(patient_rows)}")

    if stats_dir:
        continuous_stats, nominal_mappings = load_baseline_metadata(stats_dir)
    else:
        continuous_stats = _fit_continuous_stats(patient_rows)
        if shared_nominal_mappings is not None:
            nominal_mappings = shared_nominal_mappings
        else:
            nominal_mappings = fit_onehot_mappings(
                patient_rows,
                min_count=nominal_min_count,
                collapse_rare=True,
            )

    feature_schema = build_baseline_feature_schema(nominal_mappings)
    metadata_dir = Path(out_root) / "metadata"

    print("\n[2/3] 保存 metadata ...")
    save_baseline_metadata(
        metadata_dir=metadata_dir,
        encoding=BASELINE_ENCODING_NAME,
        continuous_stats=continuous_stats,
        nominal_mappings=nominal_mappings,
        feature_schema=feature_schema,
        nominal_min_count=nominal_min_count,
        mapping_scope=mapping_scope,
        save_nominal_mapping=(global_metadata_dir is None),
        save_feature_schema=(global_metadata_dir is None),
        global_metadata_dir=(Path(global_metadata_dir) if global_metadata_dir else None),
    )
    print(f"      metadata: {metadata_dir}")

    print("\n[3/3] 逐患者写入 .pt ...")
    for scheme in schemes:
        pt_dir = baseline_scheme_output_dir(out_root, scheme) / "embeddings" / "pt"
        pt_dir.mkdir(parents=True, exist_ok=True)
        fields = BASELINE_SCHEME_FIELDS[scheme]
        for row in patient_rows:
            vector = _build_baseline_vector(
                row=row,
                fields=fields,
                continuous_stats=continuous_stats,
                nominal_mappings=nominal_mappings,
            )
            torch.save(torch.from_numpy(vector), pt_dir / f"{row['patient_id']}.pt")
        print(f"      {scheme}: {pt_dir}  (dim={feature_schema[scheme]['output_dim']})")

    print("\n" + "=" * 55)
    print(f"✅  baseline 编码完成（{BASELINE_ENCODING_NAME}）")
    print(f"   患者数   : {len(patient_rows)}")
    print(f"   metadata : {metadata_dir}")
    print("=" * 55)


def global_mapping_dir() -> Path:
    return shared_global_mapping_dir()
