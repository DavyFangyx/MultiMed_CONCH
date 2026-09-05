"""Scan GDC clinical JSON and write per-dataset field dictionaries."""

from __future__ import annotations

import csv
import json
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from common.clinical_io import load_clinical_cases
from common.datasets import get_dataset_clinic_files, get_dataset_project_ids, load_dataset_configs, resolve_dataset_names
from common.paths import (
    DEFAULT_GDC_CLINICAL_DICTIONARY,
    DEFAULT_JSON_FIELD_DICT,
    LEGACY_JSON_FIELD_DICT,
    RAWDATA_STATS_ROOT,
    dataset_field_dict_path,
    resolve_reference_dict_path,
)


SECTION_PREFIX_MAP = {
    "顶层字段": "",
    "project对象": "project",
    "demographic对象": "demographic",
    "diagnoses数组_每个对象": "diagnoses[]",
    "diagnoses.pathology_details数组_每个对象": "diagnoses[].pathology_details[]",
    "diagnoses.treatments数组_每个对象": "diagnoses[].treatments[]",
    "exposures数组_每个对象": "exposures[]",
    "follow_ups数组_每个对象": "follow_ups[]",
    "follow_ups.molecular_tests数组_每个对象": "follow_ups[].molecular_tests[]",
    "follow_ups.other_clinical_attributes数组_每个对象": "follow_ups[].other_clinical_attributes[]",
}

PREFIX_SECTION_MAP = {prefix: section for section, prefix in SECTION_PREFIX_MAP.items()}

DICT_META_KEYS = {"说明", "通用字段补充说明", "_section_prefixes", "_meta"}

GENERIC_LABELS = {
    "state": "通常表示该条记录是否已发布可用（released）",
    "created_datetime": "该条子记录首次入库时间",
    "updated_datetime": "该条子记录最近更新时间",
    "submitter_id": "提交单位内部标识，便于跨表关联",
}

GDC_ENTITY_PREFIX = {
    "case": "",
    "demographic": "demographic",
    "diagnosis": "diagnoses[]",
    "pathology_detail": "diagnoses[].pathology_details[]",
    "treatment": "diagnoses[].treatments[]",
    "exposure": "exposures[]",
    "follow_up": "follow_ups[]",
    "molecular_test": "follow_ups[].molecular_tests[]",
    "other_clinical_attribute": "follow_ups[].other_clinical_attributes[]",
    "family_history": "family_histories[]",
    "project": "project",
}

FALLBACK_LABEL = "扫描发现的字段（待标注）"
ID_LABEL = "该条子记录唯一 ID（UUID）"


def dataset_json_field_dict_path(dataset_name: str) -> Path:
    return dataset_field_dict_path(dataset_name)


def load_json_field_dictionary(path) -> dict:
    dict_path = Path(path)
    with open(dict_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"字段字典必须是 JSON object: {dict_path}")
    return data


def section_prefix_map(dict_data: dict) -> dict:
    prefix_map = dict(SECTION_PREFIX_MAP)
    extra = dict_data.get("_section_prefixes") or {}
    if isinstance(extra, dict):
        for section, prefix in extra.items():
            prefix_map[str(section)] = "" if prefix is None else str(prefix)
    return prefix_map


def count_dict_fields(dict_data: dict) -> int:
    return sum(
        len(body)
        for key, body in dict_data.items()
        if key not in DICT_META_KEYS and isinstance(body, dict)
    )


def parse_field_dictionary(dict_data: dict) -> list[dict]:
    fields = []
    prefix_map = section_prefix_map(dict_data)
    for section, body in dict_data.items():
        if section in DICT_META_KEYS or not isinstance(body, dict) or section not in prefix_map:
            continue
        prefix = prefix_map[section]
        for key, zh in body.items():
            field_path = f"{prefix}.{key}" if prefix else key
            fields.append(
                {
                    "section": section,
                    "field_path": field_path,
                    "field_name": key,
                    "field_zh": str(zh),
                }
            )
    return fields


def _section_name_for_prefix(prefix: str) -> str:
    if prefix in PREFIX_SECTION_MAP:
        return PREFIX_SECTION_MAP[prefix]
    if not prefix:
        return "顶层字段"
    pretty = prefix.replace("[]", "")
    if prefix.endswith("[]"):
        return f"{pretty}数组_每个对象"
    return f"{pretty}对象"


def _is_list_of_dicts(value) -> bool:
    if not isinstance(value, list):
        return False
    return any(isinstance(item, dict) for item in value)


def _collect_keys(value, prefix: str, sections: dict) -> None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                _collect_keys(item, prefix, sections)
        return

    if not isinstance(value, dict):
        return

    bucket = sections.setdefault(prefix, set())
    for key, child in value.items():
        bucket.add(str(key))
        if isinstance(child, dict):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            _collect_keys(child, child_prefix, sections)
        elif _is_list_of_dicts(child):
            child_prefix = f"{prefix}.{key}[]" if prefix else f"{key}[]"
            for item in child:
                if isinstance(item, dict):
                    _collect_keys(item, child_prefix, sections)


def _is_gdc_dictionary_path(path: Path) -> bool:
    return path.suffix.lower() == ".csv"


def _clean_label(value) -> str:
    text = "" if value is None else str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return ""
    return text


def _load_gdc_label_bank(path: Path):
    by_section_field = {}
    by_field = {}
    field_order = {}
    csv.field_size_limit(max(csv.field_size_limit(), 8 * 1024 * 1024))
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {(k or "").lstrip("﻿"): v for k, v in row.items()}
            entity = str(row.get("entity") or "").strip()
            field = str(row.get("field") or "").strip()
            if not field:
                continue
            prefix = GDC_ENTITY_PREFIX.get(entity)
            if prefix is None:
                continue
            section = _section_name_for_prefix(prefix)
            label = _clean_label(row.get("description"))
            if not label:
                continue
            by_section_field[(section, field)] = label
            by_field.setdefault(field, label)
            field_order.setdefault(section, [])
            if field not in field_order[section]:
                field_order[section].append(field)
    return by_section_field, by_field, list(field_order), field_order


def _load_json_label_bank(reference_dict: dict):
    by_section_field = {}
    by_field = {}
    section_order = []
    field_order = {}

    generic = reference_dict.get("通用字段补充说明") or {}
    if isinstance(generic, dict):
        for key, zh in generic.items():
            if key == "各种_id字段":
                continue
            label = _clean_label(zh)
            if label:
                by_field[str(key)] = label

    for section, body in reference_dict.items():
        if section in DICT_META_KEYS or not isinstance(body, dict):
            continue
        section_order.append(section)
        field_order[section] = list(body.keys())
        for key, zh in body.items():
            label = _clean_label(zh)
            if not label:
                continue
            by_section_field[(section, str(key))] = label
            by_field.setdefault(str(key), label)

    return by_section_field, by_field, section_order, field_order


def _load_label_bank(reference_path: Path, reference_dict: dict):
    if _is_gdc_dictionary_path(reference_path) and reference_path.exists():
        return _load_gdc_label_bank(reference_path)
    return _load_json_label_bank(reference_dict)


def _label_for_field(section: str, field: str, by_section_field: dict, by_field: dict) -> str:
    if (section, field) in by_section_field:
        return by_section_field[(section, field)]
    if field in GENERIC_LABELS:
        return GENERIC_LABELS[field]
    if field in by_field:
        return by_field[field]
    if field.endswith("_id"):
        return ID_LABEL
    return FALLBACK_LABEL


def _ordered_fields(section: str, fields: set, field_order: dict) -> list:
    known = [name for name in field_order.get(section, []) if name in fields]
    extra = sorted(name for name in fields if name not in known)
    return known + extra


def build_json_field_dict(
    cases: list,
    dataset_name: str | None = None,
    source_files: list | None = None,
    reference_dict_path=None,
) -> dict:
    reference_path = resolve_reference_dict_path(reference_dict_path)
    reference_dict = {}
    if reference_path.exists() and not _is_gdc_dictionary_path(reference_path):
        reference_dict = load_json_field_dictionary(reference_path)

    by_section_field, by_field, section_order, field_order = _load_label_bank(reference_path, reference_dict)

    sections = {}
    for case in cases:
        if isinstance(case, dict):
            _collect_keys(case, "", sections)

    prefix_to_section = {prefix: _section_name_for_prefix(prefix) for prefix in sections}
    used_sections = list(dict.fromkeys(prefix_to_section.values()))
    ordered_sections = [name for name in section_order if name in used_sections]
    ordered_sections.extend(name for name in used_sections if name not in ordered_sections)

    section_prefixes = {}
    out = OrderedDict()
    dataset_label = dataset_name or "custom"
    n_cases = len(cases)
    out["说明"] = (
        f"由 {dataset_label} 的 clinical JSON 扫描生成的字段字典，"
        f"共纳入 {n_cases} 个病例。释义优先对齐 GDC clinical dictionary；"
        "不同病人出现的字段不完全一致，这里取并集。"
    )
    out["_meta"] = {
        "dataset": dataset_label,
        "n_cases": n_cases,
        "source_files": [str(x) for x in (source_files or [])],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reference_dict": str(reference_path),
    }

    generic = dict(GENERIC_LABELS)
    ref_generic = reference_dict.get("通用字段补充说明")
    if isinstance(ref_generic, dict):
        generic.update({str(k): str(v) for k, v in ref_generic.items()})

    for section in ordered_sections:
        prefix = next(p for p, name in prefix_to_section.items() if name == section)
        section_prefixes[section] = prefix
        fields = sections.get(prefix, set())
        body = OrderedDict()
        for field in _ordered_fields(section, fields, field_order):
            body[field] = _label_for_field(section, field, by_section_field, by_field)
        out[section] = body

    out["_section_prefixes"] = section_prefixes
    out["通用字段补充说明"] = generic
    return out


def write_json_field_dict(dict_data: dict, output_path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict_data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def scan_dataset_json_field_dict(
    json_paths,
    output_path,
    dataset_name: str | None = None,
    project_ids: list | None = None,
    reference_dict_path=None,
):
    cases = load_clinical_cases(json_paths, project_ids=project_ids)
    source_files = json_paths if isinstance(json_paths, list) else [json_paths]
    dict_data = build_json_field_dict(
        cases,
        dataset_name=dataset_name,
        source_files=source_files,
        reference_dict_path=reference_dict_path,
    )
    path = write_json_field_dict(dict_data, output_path)
    print(f"  字段字典已写入: {path}")
    print(
        f"  分区数: {len(dict_data.get('_section_prefixes') or {})}  "
        f"字段数: {count_dict_fields(dict_data)}"
    )
    return path, dict_data


def _is_reference_dict_path(path: Path) -> bool:
    if _is_gdc_dictionary_path(path):
        return True
    resolved = path.resolve()
    for candidate in (
        DEFAULT_GDC_CLINICAL_DICTIONARY,
        DEFAULT_JSON_FIELD_DICT,
        LEGACY_JSON_FIELD_DICT,
    ):
        if candidate.exists() and resolved == candidate.resolve():
            return True
    return False


def resolve_json_field_dict_path(dataset_name: str | None = None, explicit_path=None) -> Path:
    explicit = Path(explicit_path) if explicit_path else None
    dataset_path = dataset_json_field_dict_path(dataset_name) if dataset_name else None
    default_scan_path = dataset_json_field_dict_path(dataset_name or "custom")

    if explicit is not None and not _is_reference_dict_path(explicit):
        return explicit
    if dataset_path is not None and dataset_path.exists():
        return dataset_path
    legacy = Path(__file__).resolve().parents[2] / "templates" / "json_field_dicts" / f"{dataset_name}_json_field_dict.json" if dataset_name else None
    if legacy is not None and legacy.exists():
        return legacy
    if explicit is not None:
        return explicit
    return default_scan_path


def run_scan(args):
    datasets = load_dataset_configs(args.datasets_config)
    dataset_names = [] if not args.dataset else resolve_dataset_names(args.dataset, datasets)
    reference_dict = args.reference_dict

    if not dataset_names:
        out = Path(args.out) if args.out else RAWDATA_STATS_ROOT / "custom" / "scanned_fields.json"
        print("######## Dataset: custom ########")
        scan_dataset_json_field_dict(
            json_paths=args.json_path,
            output_path=out,
            dataset_name="custom",
            project_ids=[],
            reference_dict_path=reference_dict,
        )
        return

    for name in dataset_names:
        print(f"\n######## Dataset: {name} ########")
        out = Path(args.out) if args.out and len(dataset_names) == 1 else dataset_json_field_dict_path(name)
        scan_dataset_json_field_dict(
            json_paths=get_dataset_clinic_files(name, datasets),
            output_path=out,
            dataset_name=name,
            project_ids=get_dataset_project_ids(name, datasets),
            reference_dict_path=reference_dict,
        )
