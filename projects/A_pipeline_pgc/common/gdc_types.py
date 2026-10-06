"""GDC 字段类型分类（PGC 线本地快照）。

上游 A_pipeline/src/baseline.py 通过 `discovery.onehot` 拿这四个 helper：
`_load_gdc_dictionary` / `gdc_lookup_key` / `parse_gdc_types` / `classify_gdc_types`，
而 `discovery.onehot` 又牵出整个 discovery 包。为了本线零外部 import，这里把
**被判为等价的同一套实现**逐字搬过来，并把 GDC 词典 CSV 快照进本目录。

- 词典路径改指本地快照：A_pipeline_pgc/gdc_dictionary/gdc_clinical_dictionary.csv
- `mapping_entity` 逐字复制自 ClinicDatasets/gdc_field_tables.py（连同它依赖的
  三张常量表），避免 import ClinicDatasets。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


# --- 复制自 ClinicDatasets/gdc_field_tables.py -----------------------------

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


# --- 复制自 projects/src/discovery/onehot.py -------------------------------

GDC_DICTIONARY_PATH = (
    Path(__file__).resolve().parents[1] / "gdc_dictionary" / "gdc_clinical_dictionary.csv"
)


def _load_gdc_dictionary(path: Path | None = None) -> dict[tuple[str, str], str]:
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
