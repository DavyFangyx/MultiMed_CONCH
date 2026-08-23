"""Extract placeholder values for human-defined L0-L5 / v1 schemes."""

from common.fields import (
    get_follow_ups,
    get_other_clinical_attributes,
    get_pathology_details,
    get_primary_diagnosis,
    get_treatments,
    unique_join,
)
from common.missingness import clean_value


def extract_values(case: dict) -> dict:
    diag = get_primary_diagnosis(case.get("diagnoses", []))
    treatments = get_treatments(case)
    pathology_details = get_pathology_details(case)
    follow_ups = get_follow_ups(case)
    other_attrs = get_other_clinical_attributes(case)

    def treatment_vals(key):
        return unique_join([t.get(key, "") for t in treatments])

    def pathology_vals(key):
        return unique_join([p.get(key, "") for p in pathology_details])

    def followup_vals(key):
        return unique_join([f.get(key, "") for f in follow_ups])

    def other_attr_vals(key):
        return unique_join([a.get(key, "") for a in other_attrs])

    subtype_raw = diag.get("primary_diagnosis", "") or case.get("disease_type", "")
    subtype = clean_value(subtype_raw, "Unknown Neoplasm")

    edition_raw = diag.get("ajcc_staging_system_edition", "")
    if edition_raw:
        edition = str(edition_raw).replace("th", "").replace("st", "").replace("nd", "").replace("rd", "").strip()
    else:
        edition = "6"

    return {
        "SUBTYPE": subtype,
        "TUMORSTAGE": clean_value(diag.get("ajcc_pathologic_stage", ""), "Stage X"),
        "EDITION": edition,
        "RACE": clean_value(case.get("demographic", {}).get("race", ""), "not reported"),
        "DIAGNOSIS": clean_value(diag.get("primary_diagnosis", ""), "Unknown Neoplasm"),
        "AGE": clean_value(case.get("demographic", {}).get("age_at_index"), "unknown"),
        "SEX": clean_value(case.get("demographic", {}).get("gender", ""), "not reported"),
        "SEX_AT_BIRTH": clean_value(case.get("demographic", {}).get("sex_at_birth", ""), "not reported"),
        "ETHNICITY": clean_value(case.get("demographic", {}).get("ethnicity", ""), "not reported"),
        "PRIMARY_SITE": clean_value(case.get("primary_site", ""), "not reported"),
        "PRIMARY_DIAGNOSIS": clean_value(diag.get("primary_diagnosis", ""), "Unknown Neoplasm"),
        "MORPHOLOGY": clean_value(diag.get("morphology", ""), "not reported"),
        "TISSUE_OR_ORGAN_OF_ORIGIN": clean_value(diag.get("tissue_or_organ_of_origin", ""), "not reported"),
        "LATERALITY": clean_value(diag.get("laterality", ""), "not reported"),
        "YEAR_OF_DIAGNOSIS": clean_value(diag.get("year_of_diagnosis", ""), "not reported"),
        "AGE_AT_DIAGNOSIS": clean_value(diag.get("age_at_diagnosis", ""), "unknown"),
        "AJCC_PATHOLOGIC_STAGE": clean_value(diag.get("ajcc_pathologic_stage", ""), "Stage X"),
        "AJCC_PATHOLOGIC_T": clean_value(diag.get("ajcc_pathologic_t", ""), "TX"),
        "AJCC_PATHOLOGIC_N": clean_value(diag.get("ajcc_pathologic_n", ""), "NX"),
        "AJCC_PATHOLOGIC_M": clean_value(diag.get("ajcc_pathologic_m", ""), "MX"),
        "AJCC_STAGING_SYSTEM_EDITION": clean_value(diag.get("ajcc_staging_system_edition", ""), "not reported"),
        "TUMOR_GRADE": clean_value(diag.get("tumor_grade", ""), "not reported"),
        "PRIOR_MALIGNANCY": clean_value(diag.get("prior_malignancy", ""), "not reported"),
        "SYNCHRONOUS_MALIGNANCY": clean_value(diag.get("synchronous_malignancy", ""), "not reported"),
        "TREATMENT_TYPE": treatment_vals("treatment_type"),
        "TREATMENT_OR_THERAPY": treatment_vals("treatment_or_therapy"),
        "TREATMENT_INTENT_TYPE": treatment_vals("treatment_intent_type"),
        "PRIOR_TREATMENT": clean_value(diag.get("prior_treatment", ""), "not reported"),
        "TOBACCO_SMOKING_STATUS": clean_value(diag.get("tobacco_smoking_status", ""), "not reported"),
        "PROGRESSION_OR_RECURRENCE": clean_value(diag.get("progression_or_recurrence", ""), "not reported"),
        "LYMPH_NODES_TESTED": pathology_vals("lymph_nodes_tested"),
        "LYMPH_NODES_POSITIVE": pathology_vals("lymph_nodes_positive"),
        "ECOG_PERFORMANCE_STATUS": followup_vals("ecog_performance_status"),
        "BMI": other_attr_vals("bmi"),
    }
