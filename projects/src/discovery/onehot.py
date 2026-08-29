"""Field Bank one-hot / min-max numeric encoding."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from common.missingness import is_missing_token
from common.paths import PROJECT_ROOT
from common.types import infer_type, to_numeric
from .converters import convert_value
from .field_bank import extract_field_bank_raw_values


MISSING_TOKEN = "__MISSING__"
OTHER_TOKEN = "__OTHER__"
RARE_FREQ_THRESHOLD = 5
AGE_AT_DIAGNOSIS_LEAVES = {"AGE_AT_DIAGNOSIS", "age_at_diagnosis"}
GDC_DICTIONARY_PATH = (
    PROJECT_ROOT / "ClinicDatasets" / "gdc_clinical" / "field_tables" / "gdc_clinical_dictionary.csv"
)


def _import_mapping_entity():
    clinic_root = str(PROJECT_ROOT)
    if clinic_root not in sys.path:
        sys.path.insert(0, clinic_root)
    from ClinicDatasets.gdc_field_tables import mapping_entity

    return mapping_entity


def _load_gdc_dictionary(path: Path | None = None) -> dict[tuple[str, str], str]:
    import pandas as pd

    dict_path = Path(path or GDC_DICTIONARY_PATH)
    if not dict_path.exists():
        raise FileNotFoundError(f"未找到 GDC dictionary: {dict_path}")
    df = pd.read_csv(dict_path, dtype=str).fillna("")
    mapping = {}
    for row in df.itertuples(index=False):
        entity = str(getattr(row, "entity", "")).strip()
        field = str(getattr(row, "field", "")).strip()
        gdc_type = str(getattr(row, "type", "")).strip()
        if entity and field:
            mapping[(entity, field)] = gdc_type
    return mapping


def gdc_lookup_key(field_path: str) -> tuple[str, str]:
    mapping_entity = _import_mapping_entity()
    stripped = str(field_path).replace("[]", "")
    entity = mapping_entity(stripped)
    leaf = stripped.split(".")[-1] if stripped else ""
    return entity, leaf


def parse_gdc_types(gdc_type: str) -> list[str]:
    parts = []
    seen = set()
    for raw in str(gdc_type or "").split("|"):
        token = raw.strip().lower()
        if not token or token == "null" or token in seen:
            continue
        seen.add(token)
        parts.append(token)
    return parts


def classify_gdc_types(gdc_types: list[str]) -> str | None:
    if not gdc_types:
        return None
    if any(token in {"enum", "boolean"} for token in gdc_types):
        return "nominal"
    if all(token in {"integer", "number"} for token in gdc_types):
        return "continuous"
    if all(token == "string" for token in gdc_types):
        return None
    return None


def classify_inferred_type(inferred: str) -> str:
    if inferred == "numeric":
        return "continuous"
    return "nominal"


def _is_age_at_diagnosis(field_path: str) -> bool:
    leaf = str(field_path).replace("[]", "").split(".")[-1]
    return leaf in AGE_AT_DIAGNOSIS_LEAVES


def _converted_tokens(raw_values: list, convert: str) -> list[str]:
    tokens = []
    for value in raw_values:
        converted = convert_value(value, convert)
        text = str(converted).strip()
        if not text or is_missing_token(text):
            continue
        tokens.append(text)
    return tokens


def extract_converted_tokens(case: dict, field_path: str, convert: str) -> list[str]:
    return _converted_tokens(extract_field_bank_raw_values(case, field_path), convert)


def _numeric_from_token(token: str, field_path: str) -> float | None:
    number = to_numeric(token)
    if number is None:
        return None
    if _is_age_at_diagnosis(field_path) and number > 365:
        number = number / 365.25
    return float(number)


def aggregate_continuous(tokens: list[str], field_path: str) -> float | None:
    numbers = []
    for token in tokens:
        number = _numeric_from_token(token, field_path)
        if number is not None:
            numbers.append(number)
    if not numbers:
        return None
    return float(np.median(np.asarray(numbers, dtype=np.float64)))


def aggregate_nominal(tokens: list[str]) -> str | None:
    cleaned = []
    seen = set()
    for token in tokens:
        text = " ".join(str(token).strip().lower().split())
        if not text or is_missing_token(text) or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    if not cleaned:
        return None
    return " | ".join(sorted(cleaned))


def minmax_scale(value: float, minimum: float, maximum: float) -> float:
    if maximum == minimum:
        return 0.0
    return float((value - minimum) / (maximum - minimum))


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _lazy_torch():
    import torch

    return torch


def collect_patient_field_values(
    cases: list[dict],
    fields: list[str],
    converts: dict[str, str] | None = None,
) -> list[dict]:
    converts = converts or {}
    patients = []
    for case in cases:
        patient_id = str(case.get("submitter_id") or "").strip()
        if not patient_id:
            continue
        values = {}
        for field in fields:
            values[field] = extract_converted_tokens(case, field, converts.get(field, ""))
        patients.append({"patient_id": patient_id, "values": values})
    return patients


def infer_field_types(
    fields: list[str],
    patients: list[dict],
    dictionary: dict[tuple[str, str], str] | None = None,
) -> list[dict]:
    dictionary = dictionary if dictionary is not None else _load_gdc_dictionary()
    rows = []
    for field in fields:
        entity, leaf = gdc_lookup_key(field)
        gdc_type = dictionary.get((entity, leaf), "")
        gdc_types = parse_gdc_types(gdc_type)
        classified = classify_gdc_types(gdc_types)
        source = "gdc_dictionary"
        if classified is None:
            valid_values = []
            for patient in patients:
                valid_values.extend(patient["values"].get(field, []))
            unique_count = len(set(valid_values))
            inferred = infer_type(field, valid_values, unique_count)
            classified = classify_inferred_type(inferred)
            source = "infer_type"
        rows.append(
            {
                "field": field,
                "gdc_entity": entity,
                "gdc_type": gdc_type,
                "final_type": classified,
                "source": source,
            }
        )
    return rows


def fit_continuous_stats(field: str, patients: list[dict]) -> dict:
    numbers = []
    for patient in patients:
        value = aggregate_continuous(patient["values"].get(field, []), field)
        if value is not None:
            numbers.append(value)
    if not numbers:
        return {"min": 0.0, "max": 0.0, "median": 0.0}
    arr = np.asarray(numbers, dtype=np.float64)
    return {
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "median": float(np.median(arr)),
    }


def fit_nominal_mapping(field: str, patients: list[dict], rare_threshold: int = RARE_FREQ_THRESHOLD) -> dict[str, int]:
    counts: dict[str, int] = {}
    for patient in patients:
        category = aggregate_nominal(patient["values"].get(field, []))
        if category is None:
            continue
        counts[category] = counts.get(category, 0) + 1
    kept = sorted(cat for cat, n in counts.items() if n >= rare_threshold)
    categories = [MISSING_TOKEN, OTHER_TOKEN, *kept]
    return {cat: idx for idx, cat in enumerate(categories)}


def encode_patient_matrix(
    patient_values: dict[str, list[str]],
    field_types: list[dict],
    normalization_stats: dict[str, dict],
    category_mapping: dict[str, dict[str, int]],
    max_width: int,
) -> np.ndarray:
    matrix = np.zeros((len(field_types), max_width), dtype=np.float32)
    for i, spec in enumerate(field_types):
        field = spec["field"]
        tokens = patient_values.get(field, [])
        if spec["final_type"] == "continuous":
            stats = normalization_stats[field]
            value = aggregate_continuous(tokens, field)
            if value is None:
                value = stats["median"]
            matrix[i, 0] = minmax_scale(value, stats["min"], stats["max"])
            continue
        mapping = category_mapping[field]
        category = aggregate_nominal(tokens)
        if category is None:
            code = mapping[MISSING_TOKEN]
        else:
            code = mapping.get(category, mapping[OTHER_TOKEN])
        matrix[i, code] = 1.0
    return matrix


def build_feature_schema(
    field_types: list[dict],
    category_mapping: dict[str, dict[str, int]],
    max_width: int,
) -> dict:
    fields = []
    for i, spec in enumerate(field_types):
        field = spec["field"]
        if spec["final_type"] == "continuous":
            fields.append(
                {
                    "index": i,
                    "field": field,
                    "type": "continuous",
                    "width": 1,
                }
            )
            continue
        mapping = category_mapping[field]
        categories = [None] * len(mapping)
        for cat, idx in mapping.items():
            categories[idx] = cat
        fields.append(
            {
                "index": i,
                "field": field,
                "type": "nominal",
                "width": len(mapping),
                "categories": categories,
            }
        )
    return {
        "encoding": "onehot",
        "n_fields": len(field_types),
        "max_width": int(max_width),
        "fields": fields,
    }


def encode_onehot(
    dataset_name: str,
    cfg: dict,
    cases: list[dict],
    out_dir,
    dictionary: dict[tuple[str, str], str] | None = None,
    rare_threshold: int = RARE_FREQ_THRESHOLD,
) -> dict:
    torch = _lazy_torch()
    fields = list(cfg["fields"])
    converts = cfg.get("converts") or {}
    out_dir = Path(out_dir)
    metadata_dir = out_dir / "metadata"
    pt_dir = out_dir / "embeddings" / "pt"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    pt_dir.mkdir(parents=True, exist_ok=True)

    patients = collect_patient_field_values(cases, fields, converts)
    field_types = infer_field_types(fields, patients, dictionary=dictionary)

    normalization_stats = {}
    category_mapping = {}
    field_widths = []
    for spec in field_types:
        field = spec["field"]
        if spec["final_type"] == "continuous":
            normalization_stats[field] = fit_continuous_stats(field, patients)
            field_widths.append(1)
        else:
            mapping = fit_nominal_mapping(field, patients, rare_threshold=rare_threshold)
            category_mapping[field] = mapping
            field_widths.append(len(mapping))
    max_width = int(max(field_widths)) if field_widths else 1

    for patient in patients:
        matrix = encode_patient_matrix(
            patient["values"],
            field_types,
            normalization_stats,
            category_mapping,
            max_width,
        )
        torch.save(torch.from_numpy(matrix), pt_dir / f"{patient['patient_id']}.pt")

    schema = build_feature_schema(field_types, category_mapping, max_width)
    field_index = {
        "dataset": dataset_name,
        "encoding": "onehot",
        "fields": fields,
        "n_fields": len(fields),
        "feat_dim": max_width,
        "n_patients": len(patients),
        "rare_freq_threshold": int(rare_threshold),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _write_json(metadata_dir / "field_types.json", field_types)
    _write_json(metadata_dir / "normalization_stats.json", normalization_stats)
    _write_json(metadata_dir / "category_mapping.json", category_mapping)
    _write_json(metadata_dir / "feature_schema.json", schema)
    _write_json(out_dir / "field_index.json", field_index)
    print(f"✅ onehot embeddings: {pt_dir}  ({len(patients)} 个 .pt, shape=[{len(fields)}, {max_width}])")
    print(f"✅ field_index.json: {out_dir / 'field_index.json'}")
    return {
        "out_dir": out_dir,
        "n_fields": len(fields),
        "max_width": max_width,
        "n_patients": len(patients),
        "field_types": field_types,
        "schema": schema,
    }
