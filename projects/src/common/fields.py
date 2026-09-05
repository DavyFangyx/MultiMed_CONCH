"""Field-path parsing and nested JSON extraction."""

from __future__ import annotations

import json

from .missingness import clean_value
from .types import to_numeric


def is_array_field(field_path: str) -> bool:
    return "[]" in (field_path or "")


L5_FIELDS = [
    "demographic.age_at_index",
    "demographic.sex_at_birth",
    "demographic.race",
    "demographic.ethnicity",
    "diagnoses[].primary_diagnosis",
    "diagnoses[].morphology",
    "diagnoses[].tissue_or_organ_of_origin",
    "diagnoses[].laterality",
    "diagnoses[].year_of_diagnosis",
    "diagnoses[].age_at_diagnosis",
    "diagnoses[].tumor_grade",
    "diagnoses[].prior_malignancy",
    "diagnoses[].synchronous_malignancy",
    "diagnoses[].prior_treatment",
    "diagnoses[].ajcc_pathologic_t",
    "diagnoses[].ajcc_pathologic_n",
    "diagnoses[].ajcc_pathologic_m",
    "diagnoses[].ajcc_pathologic_stage",
    "diagnoses[].ajcc_staging_system_edition",
    "diagnoses[].pathology_details[].lymph_nodes_tested",
    "diagnoses[].pathology_details[].lymph_nodes_positive",
    "follow_ups[].ecog_performance_status",
    "follow_ups[].other_clinical_attributes[].bmi",
]

PAPER_FIELDS = [
    "project.project_id",
    "diagnoses[].primary_diagnosis",
    "derived.pharmaceutical_therapy",
    "derived.radiation_therapy",
    "exposures[].pack_years_smoked",
    "derived.years_smoked",
    "exposures[].cigarettes_per_day",
    "exposures[].alcohol_history",
    "diagnoses[].site_of_resection_or_biopsy",
]

HUMAN_SCHEME_FIELDS = list(dict.fromkeys([*L5_FIELDS, *PAPER_FIELDS]))

# Derived fields reuse a source GDC path for dictionary lookup / stats labels,
# but keep a unique field id so they do not collide with that source field.
DERIVED_FIELD_SOURCE_PATH = {
    "derived.pharmaceutical_therapy": "diagnoses[].treatments[].treatment_or_therapy",
    "derived.radiation_therapy": "diagnoses[].treatments[].treatment_or_therapy",
    "derived.years_smoked": "exposures[].exposure_duration_years",
}

DERIVED_FIELD_TYPES = {
    "derived.years_smoked": "continuous",
}

L5_FIELD_PATH_BY_PLACEHOLDER = {
    "AGE": "demographic.age_at_index",
    "SEX_AT_BIRTH": "demographic.sex_at_birth",
    "RACE": "demographic.race",
    "ETHNICITY": "demographic.ethnicity",
    "PRIMARY_DIAGNOSIS": "diagnoses[].primary_diagnosis",
    "MORPHOLOGY": "diagnoses[].morphology",
    "TISSUE_OR_ORGAN_OF_ORIGIN": "diagnoses[].tissue_or_organ_of_origin",
    "LATERALITY": "diagnoses[].laterality",
    "YEAR_OF_DIAGNOSIS": "diagnoses[].year_of_diagnosis",
    "AGE_AT_DIAGNOSIS": "diagnoses[].age_at_diagnosis",
    "TUMOR_GRADE": "diagnoses[].tumor_grade",
    "PRIOR_MALIGNANCY": "diagnoses[].prior_malignancy",
    "SYNCHRONOUS_MALIGNANCY": "diagnoses[].synchronous_malignancy",
    "PRIOR_TREATMENT": "diagnoses[].prior_treatment",
    "AJCC_PATHOLOGIC_T": "diagnoses[].ajcc_pathologic_t",
    "AJCC_PATHOLOGIC_N": "diagnoses[].ajcc_pathologic_n",
    "AJCC_PATHOLOGIC_M": "diagnoses[].ajcc_pathologic_m",
    "AJCC_PATHOLOGIC_STAGE": "diagnoses[].ajcc_pathologic_stage",
    "AJCC_STAGING_SYSTEM_EDITION": "diagnoses[].ajcc_staging_system_edition",
    "LYMPH_NODES_TESTED": "diagnoses[].pathology_details[].lymph_nodes_tested",
    "LYMPH_NODES_POSITIVE": "diagnoses[].pathology_details[].lymph_nodes_positive",
    "ECOG_PERFORMANCE_STATUS": "follow_ups[].ecog_performance_status",
    "BMI": "follow_ups[].other_clinical_attributes[].bmi",
}
L5_PLACEHOLDER_BY_FIELD_PATH = {
    path: placeholder for placeholder, path in L5_FIELD_PATH_BY_PLACEHOLDER.items()
}


def field_output_col(field: str) -> str:
    return str(field).replace(".", "_").replace("[]", "") + "_template"


def field_gdc_path(field: str) -> str:
    return DERIVED_FIELD_SOURCE_PATH.get(field, field)


def parse_field_path(field_path: str) -> list[tuple[str, bool]]:
    tokens = []
    for token in str(field_path).split(".") if field_path else []:
        is_array = token.endswith("[]")
        key = token[:-2] if is_array else token
        tokens.append((key, is_array))
    return tokens


def extract_path_values(case: dict, field_path: str) -> list:
    nodes = [case]
    for key, is_array in parse_field_path(field_path):
        nxt = []
        for node in nodes:
            if not isinstance(node, dict) or key not in node:
                continue
            val = node.get(key)
            if is_array:
                if isinstance(val, list):
                    nxt.extend(val)
            else:
                nxt.append(val)
        nodes = nxt
    return nodes


def unique_join(values: list, fallback="not reported") -> str:
    vals = [clean_value(v, "") for v in values]
    vals = sorted({x for x in vals if x})
    return ", ".join(vals) if vals else fallback


def get_primary_diagnosis(diagnoses: list) -> dict:
    if not diagnoses:
        return {}
    for item in diagnoses:
        if str(item.get("diagnosis_is_primary_disease", "")).lower() == "true":
            return item
    return diagnoses[0]


def get_treatments(case: dict) -> list:
    treatments = case.get("treatments", [])
    if not treatments:
        for diag in case.get("diagnoses", []):
            treatments = diag.get("treatments", [])
            if treatments:
                break
    return treatments or []


def get_pathology_details(case: dict) -> list:
    details = []
    for diag in case.get("diagnoses", []):
        details.extend(diag.get("pathology_details", []) or [])
    return details


def get_follow_ups(case: dict) -> list:
    return case.get("follow_ups", []) or []


def get_other_clinical_attributes(case: dict) -> list:
    attrs = []
    for follow_up in get_follow_ups(case):
        attrs.extend(follow_up.get("other_clinical_attributes", []) or [])
    return attrs


def collapse_patient_values(values: list):
    if not values:
        return None

    scalar_vals = []
    for item in values:
        if isinstance(item, (dict, list)):
            scalar_vals.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
        else:
            scalar_vals.append(str(item).strip())

    nums = []
    all_numeric = True
    for item in scalar_vals:
        number = to_numeric(item)
        if number is None:
            all_numeric = False
            break
        nums.append(number)

    if all_numeric and nums:
        return sum(nums) / len(nums)

    uniq = sorted(set(scalar_vals))
    if len(uniq) == 1:
        return uniq[0]
    return " | ".join(uniq)
