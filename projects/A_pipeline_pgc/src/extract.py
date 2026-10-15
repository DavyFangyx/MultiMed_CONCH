"""Extract human-scheme field values from clinical JSON.

PGC 线：无 landmark 协议,`extract_values` 不再接收 landmark_time —— 上游
`mask_case(case, None)` 本来就是原样返回 case,所以取值逐字一致。
"""

from __future__ import annotations

import json

from common.fields import (
    get_follow_ups,
    get_other_clinical_attributes,
    get_pathology_details,
    get_primary_diagnosis,
    unique_join,
)
from common.missingness import clean_value
from common.types import to_numeric

from .paths import A_PIPELINE_PGC_ROOT


PHARMA_TREATMENT_TYPE = "pharmaceutical therapy, nos"
RADIATION_TREATMENT_TYPE = "radiation therapy, nos"

# 取值别名映射（借鉴 gdc 线 R5_alias 的声明式规则机制）：同语义、不同源表口径的取值
# 对齐到 GDC/TCGA canonical 口径。规则文件随 templates/ 冻结；无规则命中时原样返回。
_VALUE_ALIAS_RULES_PATH = A_PIPELINE_PGC_ROOT / "templates" / "value_alias_rules.json"
_value_alias_rules_cache: dict | None = None


def _load_value_alias_rules() -> dict:
    global _value_alias_rules_cache
    if _value_alias_rules_cache is None:
        if _VALUE_ALIAS_RULES_PATH.exists():
            with open(_VALUE_ALIAS_RULES_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            _value_alias_rules_cache = raw.get("aliases", {})
        else:
            _value_alias_rules_cache = {}
    return _value_alias_rules_cache


def _normalize_alias_key(value) -> str:
    return " ".join(str(value).strip().lower().split())


def _apply_value_alias(field: str, raw_value) -> str:
    """源表取值 → canonical 取值;空串映射 = 缺失,由调用处既有 fallback 链兜底。"""
    text = "" if raw_value is None else str(raw_value)
    rules = _load_value_alias_rules().get(field) or {}
    mapping = rules.get("map", {})
    key = _normalize_alias_key(text)
    if key in mapping:
        return mapping[key]
    return text.strip()


def _first_nonempty(values: list, fallback: str) -> str:
    for value in values:
        cleaned = clean_value(value, "")
        if cleaned:
            return cleaned
    return fallback


def _ordered_diagnoses(case: dict) -> list[dict]:
    diagnoses = list(case.get("diagnoses", []) or [])
    if not diagnoses:
        return []
    primary = get_primary_diagnosis(diagnoses)
    rest = [item for item in diagnoses if item is not primary]
    return [primary, *rest]


def _all_treatments(case: dict) -> list[dict]:
    treatments = []
    for diagnosis in _ordered_diagnoses(case):
        treatments.extend(diagnosis.get("treatments", []) or [])
    treatments.extend(case.get("treatments", []) or [])
    return treatments


def _therapy_flag(case: dict, treatment_type: str, fallback: str = "unknown") -> str:
    matched = []
    for treatment in _all_treatments(case):
        raw_type = str(treatment.get("treatment_type", "")).strip().lower()
        if raw_type != treatment_type:
            continue
        token = clean_value(treatment.get("treatment_or_therapy", ""), "")
        if token:
            matched.append(token.lower())
    if any(token == "yes" for token in matched):
        return "yes"
    if any(token == "no" for token in matched):
        return "no"
    return fallback


def _exposure_values(case: dict, key: str) -> list:
    return [item.get(key) for item in (case.get("exposures", []) or [])]


def _format_number(value) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


def _years_smoked(case: dict, year_of_diagnosis, age_at_index) -> str:
    for exposure in case.get("exposures", []) or []:
        duration = to_numeric(exposure.get("exposure_duration_years"))
        if duration is not None:
            return _format_number(duration)

        onset_year = to_numeric(exposure.get("tobacco_smoking_onset_year"))
        quit_year = to_numeric(exposure.get("tobacco_smoking_quit_year"))
        diagnosis_year = to_numeric(year_of_diagnosis)
        if onset_year is not None and quit_year is not None:
            return _format_number(quit_year - onset_year)
        if onset_year is not None and diagnosis_year is not None:
            return _format_number(diagnosis_year - onset_year)

        age_at_onset = to_numeric(exposure.get("age_at_onset"))
        index_age = to_numeric(age_at_index)
        if age_at_onset is not None and index_age is not None:
            return _format_number(index_age - age_at_onset)
    return "unknown"


def extract_values(case: dict) -> dict:
    """Field values for one case (no landmark mask; `case` used as is)."""
    diag = get_primary_diagnosis(case.get("diagnoses", []))
    pathology_details = get_pathology_details(case)
    follow_ups = get_follow_ups(case)
    other_attrs = get_other_clinical_attributes(case)
    demographic = case.get("demographic", {}) or {}

    def pathology_vals(key):
        return unique_join([p.get(key, "") for p in pathology_details])

    def followup_vals(key):
        return unique_join([f.get(key, "") for f in follow_ups])

    def other_attr_vals(key):
        return unique_join([a.get(key, "") for a in other_attrs])

    age = clean_value(demographic.get("age_at_index"), "unknown")
    year_of_diagnosis = clean_value(diag.get("year_of_diagnosis", ""), "not reported")
    sex = _first_nonempty(
        [demographic.get("sex_at_birth", ""), demographic.get("gender", "")],
        "not reported",
    )
    primary_diagnosis = clean_value(diag.get("primary_diagnosis", ""), "Unknown Neoplasm")
    pathologic_stage = _apply_value_alias(
        "diagnoses[].ajcc_pathologic_stage",
        diag.get("ajcc_pathologic_stage", ""),
    )
    pathologic_stage = clean_value(pathologic_stage, "")
    staging_edition = clean_value(diag.get("ajcc_staging_system_edition", ""), "")

    return {
        "demographic.age_at_index": age,
        "demographic.sex_at_birth": sex,
        "demographic.race": clean_value(demographic.get("race", ""), "not reported"),
        "demographic.ethnicity": clean_value(demographic.get("ethnicity", ""), "not reported"),
        "diagnoses[].primary_diagnosis": primary_diagnosis,
        "diagnoses[].morphology": clean_value(diag.get("morphology", ""), "not reported"),
        "diagnoses[].tissue_or_organ_of_origin": clean_value(diag.get("tissue_or_organ_of_origin", ""), "not reported"),
        "diagnoses[].laterality": clean_value(diag.get("laterality", ""), "not reported"),
        "diagnoses[].year_of_diagnosis": year_of_diagnosis,
        "diagnoses[].age_at_diagnosis": clean_value(diag.get("age_at_diagnosis", ""), "unknown"),
        "diagnoses[].tumor_grade": clean_value(diag.get("tumor_grade", ""), "not reported"),
        "diagnoses[].prior_malignancy": clean_value(diag.get("prior_malignancy", ""), "not reported"),
        "diagnoses[].synchronous_malignancy": clean_value(diag.get("synchronous_malignancy", ""), "not reported"),
        "diagnoses[].prior_treatment": clean_value(diag.get("prior_treatment", ""), "not reported"),
        "diagnoses[].ajcc_pathologic_t": clean_value(diag.get("ajcc_pathologic_t", ""), "TX"),
        "diagnoses[].ajcc_pathologic_n": clean_value(diag.get("ajcc_pathologic_n", ""), "NX"),
        "diagnoses[].ajcc_pathologic_m": clean_value(diag.get("ajcc_pathologic_m", ""), "MX"),
        "diagnoses[].ajcc_pathologic_stage": pathologic_stage or clean_value(diag.get("figo_stage", ""), "Stage X"),
        "diagnoses[].ajcc_staging_system_edition": staging_edition
        or clean_value(diag.get("figo_staging_edition_year", ""), "not reported"),
        "diagnoses[].pathology_details[].lymph_nodes_tested": pathology_vals("lymph_nodes_tested"),
        "diagnoses[].pathology_details[].lymph_nodes_positive": pathology_vals("lymph_nodes_positive"),
        "follow_ups[].ecog_performance_status": followup_vals("ecog_performance_status"),
        "follow_ups[].other_clinical_attributes[].bmi": other_attr_vals("bmi"),
        "project.project_id": clean_value(case.get("project", {}).get("project_id", ""), "not reported"),
        "derived.pharmaceutical_therapy": _therapy_flag(case, PHARMA_TREATMENT_TYPE),
        "derived.radiation_therapy": _therapy_flag(case, RADIATION_TREATMENT_TYPE),
        "exposures[].pack_years_smoked": unique_join(_exposure_values(case, "pack_years_smoked"), "unknown"),
        "derived.years_smoked": _years_smoked(case, year_of_diagnosis, age),
        "exposures[].cigarettes_per_day": unique_join(_exposure_values(case, "cigarettes_per_day"), "unknown"),
        "exposures[].alcohol_history": unique_join(_exposure_values(case, "alcohol_history"), "not reported"),
        "diagnoses[].site_of_resection_or_biopsy": clean_value(
            diag.get("site_of_resection_or_biopsy", ""),
            "not reported",
        ),
    }
