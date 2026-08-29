#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gdc_field_tables.py — 从 GDC API 导出两张 clinic 字段表，不下载病例数据。

两张表都是 schema，不是 TCGA 病例本身。它们描述 ClinicDatasets/gdc_clinical/raw_json
里已经下好的门户 clinical JSON：嵌套字段分别来自这些 Clinical 实体。

  1. Data Dictionary（Clinical 类别）
     GET /v0/submission/_dictionary/_all
     -> gdc_clinical/field_tables/gdc_clinical_dictionary.csv
     实体：case, demographic, diagnosis, treatment, exposure, follow_up,
           family_history, pathology_detail, molecular_test
     以及 dictionary 里 category=clinical 的其它实体（例如 other_clinical_attribute）。
     case 只保留病例根字段和 clinic 关联，去掉 samples / files / aliquots 等。

  2. cases 字段全集（clinical JSON 可查询字段）
     GET /cases/_mapping
     -> gdc_clinical/field_tables/gdc_cases_mapping.csv

从项目根目录调用。输出目录写死，没有 --outdir。

python ClinicDatasets/gdc_field_tables.py
python ClinicDatasets/gdc_field_tables.py --timeout 180

依赖：pip install requests pandas
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

def _import_requests():
    import requests
    from requests.adapters import HTTPAdapter

    try:
        from urllib3.util.retry import Retry
    except ImportError:
        from requests.packages.urllib3.util.retry import Retry
    return requests, HTTPAdapter, Retry


API = "https://api.gdc.cancer.gov"

# 门户 clinical JSON 的嵌套来源。case 是根节点，其余是 Clinical 类别下的实体。
CLINICAL_ENTITIES = (
    "case",
    "demographic",
    "diagnosis",
    "treatment",
    "exposure",
    "follow_up",
    "family_history",
    "pathology_detail",
    "molecular_test",
)

# case 实体里这些是 biospecimen / 文件链接，不是 clinic。
CASE_SKIP_FIELDS = {
    "samples",
    "files",
    "aliquots",
    "portions",
    "analytes",
    "slides",
    "read_groups",
    "annotations",
    "tissue_source_site",
    "tissue_source_sites",
    "projects",
}

# /cases/_mapping 里临床分析会用到的前缀；和 gdc_clinical_batch.py 的 A 分支对齐。
CLINICAL_CASE_FIELDS = {
    "case_id",
    "submitter_id",
    "disease_type",
    "primary_site",
    "lost_to_followup",
    "days_to_lost_to_followup",
    "consent_type",
    "days_to_consent",
    "index_date",
    "state",
    "updated_datetime",
    "project.project_id",
}
CLINICAL_PREFIXES = (
    "demographic.",
    "diagnoses.",
    "exposures.",
    "family_histories.",
    "follow_ups.",
)
CLINICAL_SKIP_PREFIXES = (
    "diagnoses.annotations.",
    "follow_ups.annotations.",
)

MAPPING_ROOT_TO_ENTITY = {
    "demographic": "demographic",
    "diagnoses": "diagnosis",
    "exposures": "exposure",
    "family_histories": "family_history",
    "follow_ups": "follow_up",
    "project": "project",
}
MAPPING_NESTED_TO_ENTITY = {
    "treatments": "treatment",
    "pathology_details": "pathology_detail",
    "molecular_tests": "molecular_test",
    "other_clinical_attributes": "other_clinical_attribute",
    "family_histories": "family_history",
}

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "gdc_clinical" / "field_tables"


def make_session(retries=5, timeout=120):
    requests, HTTPAdapter, Retry = _import_requests()
    s = requests.Session()
    retry = Retry(
        total=retries, connect=retries, read=retries,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=8)
    s.mount("https://", adapter)
    s.request_timeout = timeout
    return s


def api_get(sess, path):
    url = path if path.startswith("http") else f"{API}/{path.lstrip('/')}"
    r = sess.get(url, timeout=sess.request_timeout)
    r.raise_for_status()
    return r.json()


def get_data_release(sess):
    try:
        return sess.get(f"{API}/status", timeout=30).json()
    except Exception as e:
        return {"error": str(e)}


def format_type(prop):
    if not isinstance(prop, dict):
        return str(prop or "")
    if prop.get("enum"):
        return "enum"
    if "oneOf" in prop:
        parts = [format_type(p) for p in prop["oneOf"] if isinstance(p, dict)]
        return "|".join(p for p in parts if p)
    if "anyOf" in prop:
        parts = [format_type(p) for p in prop["anyOf"] if isinstance(p, dict)]
        return "|".join(p for p in parts if p)
    t = prop.get("type")
    if isinstance(t, list):
        return "|".join(str(x) for x in t)
    if t == "array":
        items = prop.get("items") or {}
        inner = format_type(items) if items else ""
        return f"array[{inner}]" if inner else "array"
    if t:
        return str(t)
    if "$ref" in prop:
        return str(prop["$ref"])
    return ""


def collect_enum(prop):
    if not isinstance(prop, dict):
        return []
    vals = []
    if "enum" in prop and isinstance(prop["enum"], list):
        vals.extend(prop["enum"])
    for key in ("oneOf", "anyOf"):
        for branch in prop.get(key) or []:
            vals.extend(collect_enum(branch))
    items = prop.get("items")
    if isinstance(items, dict):
        vals.extend(collect_enum(items))
    seen = set()
    out = []
    for v in vals:
        s = str(v)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def term_info(prop):
    term = ((prop.get("term") or {}).get("termDef") or {}) if isinstance(prop, dict) else {}
    return {
        "cde_id": term.get("cde_id", ""),
        "cde_version": term.get("cde_version", ""),
        "term": term.get("term", ""),
        "term_source": term.get("source", ""),
        "term_url": term.get("term_url", ""),
    }


def is_clinical_entity(name, schema):
    # 旧的 clinical 包装节点不是用户列出的实体，跳过。
    if name.startswith("_") or name == "clinical":
        return False
    if name in CLINICAL_ENTITIES:
        return True
    return (schema or {}).get("category") == "clinical"


def flatten_dictionary(all_dict):
    rows = []
    kept = []
    for name, schema in sorted(all_dict.items()):
        if not isinstance(schema, dict):
            continue
        if not is_clinical_entity(name, schema):
            continue
        kept.append(name)
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        system_props = set(schema.get("systemProperties") or [])
        title = schema.get("title") or name
        category = schema.get("category") or ""
        for field, prop in sorted(props.items()):
            if name == "case" and field in CASE_SKIP_FIELDS:
                continue
            if not isinstance(prop, dict):
                prop = {"description": str(prop)}
            enums = collect_enum(prop)
            info = term_info(prop)
            rows.append({
                "entity": name,
                "category": category,
                "entity_title": title,
                "field": field,
                "type": format_type(prop),
                "required": "yes" if field in required else "no",
                "system_property": "yes" if field in system_props else "no",
                "description": prop.get("description") or "",
                "enum": " | ".join(enums),
                "n_enum": len(enums),
                "minimum": prop.get("minimum", ""),
                "maximum": prop.get("maximum", ""),
                **info,
            })
    return rows, kept


def mapping_entity(field):
    parts = field.split(".")
    if not parts:
        return "case"
    root = parts[0]
    for part in reversed(parts[:-1]):
        if part in MAPPING_NESTED_TO_ENTITY:
            return MAPPING_NESTED_TO_ENTITY[part]
    if root in MAPPING_ROOT_TO_ENTITY:
        return MAPPING_ROOT_TO_ENTITY[root]
    if field in CLINICAL_CASE_FIELDS or "." not in field:
        return "case"
    return root


def is_clinical_mapping_field(field):
    if field.startswith(CLINICAL_SKIP_PREFIXES):
        return False
    if field in CLINICAL_CASE_FIELDS:
        return True
    return field.startswith(CLINICAL_PREFIXES)


def flatten_mapping(payload, clinical_only=True):
    fields = payload.get("fields") or []
    mapping = payload.get("_mapping") or {}
    rows = []
    for field in sorted(fields):
        clinic = is_clinical_mapping_field(field)
        if clinical_only and not clinic:
            continue
        info = mapping.get(field) or {}
        rows.append({
            "field": field,
            "entity": mapping_entity(field),
            "type": info.get("type", ""),
            "description": info.get("description", ""),
            "in_clinical_json": "yes" if clinic else "no",
        })
    return rows


def write_csv(path, rows, columns):
    import pandas as pd

    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=columns)
    df.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    return df


def main():
    ap = argparse.ArgumentParser(description="导出 GDC clinic Data Dictionary 和 cases/_mapping 字段表")
    ap.add_argument("--retries", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument(
        "--include-nonclinical-mapping",
        action="store_true",
        help="mapping 表保留 /cases 全部字段；默认只留 clinical JSON 用得到的字段",
    )
    args = ap.parse_args()

    sess = make_session(retries=args.retries, timeout=args.timeout)
    status = get_data_release(sess)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1] Data Dictionary  clinic 实体")
    all_dict = api_get(sess, "v0/submission/_dictionary/_all")
    dict_rows, kept_entities = flatten_dictionary(all_dict)
    dict_cols = [
        "entity", "category", "entity_title", "field", "type", "required",
        "system_property", "description", "enum", "n_enum", "minimum", "maximum",
        "cde_id", "cde_version", "term", "term_source", "term_url",
    ]
    dict_path = OUT_DIR / "gdc_clinical_dictionary.csv"
    dict_df = write_csv(dict_path, dict_rows, dict_cols)
    print("  实体 %d 个: %s" % (len(kept_entities), ", ".join(kept_entities)))
    print("  %d 行 -> %s" % (len(dict_df), dict_path))

    print("[2] /cases/_mapping  clinical 字段")
    mapping_payload = api_get(sess, "cases/_mapping")
    map_rows = flatten_mapping(
        mapping_payload,
        clinical_only=not args.include_nonclinical_mapping,
    )
    map_cols = ["field", "entity", "type", "description", "in_clinical_json"]
    map_path = OUT_DIR / "gdc_cases_mapping.csv"
    map_df = write_csv(map_path, map_rows, map_cols)
    print("  %d 行 -> %s" % (len(map_df), map_path))

    meta = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "gdc_status": status,
        "dictionary_entities": kept_entities,
        "n_dictionary_fields": int(len(dict_df)),
        "n_mapping_fields": int(len(map_df)),
        "n_mapping_fields_all": len(mapping_payload.get("fields") or []),
        "clinical_only_mapping": not args.include_nonclinical_mapping,
        "outputs": {
            "dictionary": str(dict_path),
            "mapping": str(map_path),
        },
    }
    meta_path = OUT_DIR / "run_metadata.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  metadata -> %s" % meta_path)
    print("完成。输出在 %s" % OUT_DIR)


if __name__ == "__main__":
    main()

