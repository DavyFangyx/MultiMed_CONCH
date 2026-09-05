"""Shared Field Bank convert / unit / template rules."""

from __future__ import annotations

import csv
from pathlib import Path

import re

import pandas as pd

from common.paths import (
    DEFAULT_GDC_CASES_MAPPING,
    DEFAULT_GDC_CLINICAL_DICTIONARY,
    PROJECT_ROOT,
)
from .converters import known_converters
from .filter import apply_rules, load_filter_rules

SPEC_COLUMNS = ["field", "convert", "unit", "template", "note"]
SHARED_SPEC_PATH = PROJECT_ROOT / "templates" / "field_bank" / "_shared" / "field_prompt_spec.csv"

DAYS_TO_YEARS_FIELDS = {
    "diagnoses[].age_at_diagnosis",
}

ARRAY_PREFIX = {
    "diagnoses": "diagnoses[]",
    "treatments": "treatments[]",
    "pathology_details": "pathology_details[]",
    "exposures": "exposures[]",
    "family_histories": "family_histories[]",
    "follow_ups": "follow_ups[]",
    "molecular_tests": "molecular_tests[]",
    "other_clinical_attributes": "other_clinical_attributes[]",
}

UNIT_OVERRIDES = {
    "exposures[].pack_years_smoked": "pack-years",
}

_OFFICIAL_META: dict[str, dict[str, str]] | None = None

_EXISTING_TEMPLATES: dict[str, str] | None = None

TEMPLATE_OVERRIDES = {
    "demographic.age_is_obfuscated": "Age is obfuscated: {}.",
    "demographic.country_of_birth": "Country of birth is {}.",
    "demographic.country_of_residence_at_enrollment": "Country of residence at enrollment is {}.",
    "demographic.ethnicity": "Ethnicity is {}.",
    "demographic.race": "Race is {}.",
    "demographic.sex_at_birth": "Sex at birth is {}.",
    "demographic.year_of_birth": "Year of birth is {}.",
    "diagnoses[].age_at_diagnosis": "Age at diagnosis is {} years.",
    "diagnoses[].ajcc_clinical_m": "Clinical M stage is {}.",
    "diagnoses[].ajcc_clinical_n": "Clinical N stage is {}.",
    "diagnoses[].ajcc_clinical_stage": "Clinical stage is {}.",
    "diagnoses[].ajcc_clinical_t": "Clinical T stage is {}.",
    "diagnoses[].ajcc_pathologic_m": "Pathologic M stage is {}.",
    "diagnoses[].ajcc_pathologic_n": "Pathologic N stage is {}.",
    "diagnoses[].ajcc_pathologic_t": "Pathologic T stage is {}.",
    "diagnoses[].ajcc_serum_tumor_markers": "AJCC serum tumor markers are {}.",
    "diagnoses[].ann_arbor_b_symptoms": "Ann Arbor B symptoms is {}.",
    "diagnoses[].ann_arbor_clinical_stage": "Ann Arbor clinical stage is {}.",
    "diagnoses[].ann_arbor_extranodal_involvement": "Ann Arbor extranodal involvement is {}.",
    "diagnoses[].calgb_risk_group": "CALGB risk group is {}.",
    "diagnoses[].cancer_detection_method": "Cancer detection method is {}.",
    "diagnoses[].child_pugh_classification": "Child-Pugh classification is {}.",
    "diagnoses[].clark_level": "Clark level is {}.",
    "diagnoses[].diagnosis_is_primary_disease": "The diagnosis is the primary disease: {}.",
    "diagnoses[].ensat_clinical_m": "ENSAT clinical M stage is {}.",
    "diagnoses[].ensat_pathologic_n": "ENSAT pathologic N stage is {}.",
    "diagnoses[].ensat_pathologic_stage": "ENSAT pathologic stage is {}.",
    "diagnoses[].ensat_pathologic_t": "ENSAT pathologic T stage is {}.",
    "diagnoses[].esophageal_columnar_dysplasia_degree": "Esophageal columnar dysplasia degree is {}.",
    "diagnoses[].esophageal_columnar_metaplasia_present": "Esophageal columnar metaplasia present is {}.",
    "diagnoses[].fab_morphology_code": "FAB morphology code is {}.",
    "diagnoses[].figo_stage": "FIGO stage is {}.",
    "diagnoses[].figo_staging_edition_year": "FIGO staging edition year is {}.",
    "diagnoses[].first_symptom_longest_duration": "Longest first-symptom duration is {}.",
    "diagnoses[].first_symptom_prior_to_diagnosis": "First symptom prior to diagnosis is {}.",
    "diagnoses[].gleason_score": "Gleason score is {}.",
    "diagnoses[].goblet_cells_columnar_mucosa_present": "Goblet cells in columnar mucosa present is {}.",
    "diagnoses[].icd_10_code": "ICD-10 code is {}.",
    "diagnoses[].ishak_fibrosis_score": "Ishak fibrosis score is {}.",
    "diagnoses[].laterality": "Laterality is {}.",
    "diagnoses[].masaoka_stage": "Masaoka stage is {}.",
    "diagnoses[].max_tumor_bulk_site": "Maximum tumor bulk site is {}.",
    "diagnoses[].melanoma_known_primary": "Melanoma known primary is {}.",
    "diagnoses[].metastasis_at_diagnosis": "Metastasis at diagnosis is {}.",
    "diagnoses[].method_of_diagnosis": "Method of diagnosis is {}.",
    "diagnoses[].morphology": "Tumor morphology is {}.",
    "diagnoses[].pathology_details[].additional_pathology_findings": "Additional pathology findings are {}.",
    "diagnoses[].pathology_details[].bone_marrow_malignant_cells": "Bone marrow malignant cells present is {}.",
    "diagnoses[].pathology_details[].breslow_thickness_category": "Breslow thickness category is {}.",
    "diagnoses[].pathology_details[].circumferential_resection_margin": "Circumferential resection margin is {}.",
    "diagnoses[].pathology_details[].consistent_pathology_review": "Consistent pathology review is {}.",
    "diagnoses[].pathology_details[].epithelioid_cell_percent_range": "Epithelioid cell percent range is {}.",
    "diagnoses[].pathology_details[].extracapsular_extension_present": "Extracapsular extension present is {}.",
    "diagnoses[].pathology_details[].extranodal_extension": "Extranodal extension is {}.",
    "diagnoses[].pathology_details[].extrascleral_extension_present": "Extrascleral extension present is {}.",
    "diagnoses[].pathology_details[].extrathyroid_extension": "Extrathyroid extension is {}.",
    "diagnoses[].pathology_details[].greatest_tumor_dimension": "Greatest tumor dimension is {} cm.",
    "diagnoses[].pathology_details[].intratubular_germ_cell_neoplasia_present": "Intratubular germ cell neoplasia present is {}.",
    "diagnoses[].pathology_details[].lymph_node_dissection_method": "Lymph node dissection method is {}.",
    "diagnoses[].pathology_details[].lymph_node_dissection_site": "Lymph node dissection site is {}.",
    "diagnoses[].pathology_details[].lymph_node_involved_site": "Lymph node involved site is {}.",
    "diagnoses[].pathology_details[].lymph_node_involvement": "Lymph node involvement is {}.",
    "diagnoses[].pathology_details[].lymph_nodes_positive": "Number of positive lymph nodes is {}.",
    "diagnoses[].pathology_details[].lymph_nodes_removed": "Lymph nodes removed is {}.",
    "diagnoses[].pathology_details[].lymph_nodes_tested": "Number of tested lymph nodes is {}.",
    "diagnoses[].pathology_details[].lymphatic_invasion_present": "Lymphatic invasion present is {}.",
    "diagnoses[].pathology_details[].margin_status": "Pathology margin status is {}.",
    "diagnoses[].pathology_details[].measurement_type": "Pathology measurement type is {}.",
    "diagnoses[].pathology_details[].micrometastasis_present": "Micrometastasis present is {}.",
    "diagnoses[].pathology_details[].necrosis_percent": "Necrosis percent is {}%.",
    "diagnoses[].pathology_details[].necrosis_present": "Necrosis present is {}.",
    "diagnoses[].pathology_details[].non_nodal_tumor_deposits": "Non-nodal tumor deposits present is {}.",
    "diagnoses[].pathology_details[].percent_tumor_invasion": "Percent tumor invasion is {}%.",
    "diagnoses[].pathology_details[].perineural_invasion_present": "Perineural invasion present is {}.",
    "diagnoses[].pathology_details[].prcc_type": "PRCC type is {}.",
    "diagnoses[].pathology_details[].residual_tumor_measurement": "Residual tumor measurement is {}.",
    "diagnoses[].pathology_details[].sarcomatoid_present": "Sarcomatoid present is {}.",
    "diagnoses[].pathology_details[].spindle_cell_percent_range": "Spindle cell percent range is {}.",
    "diagnoses[].pathology_details[].timepoint_category": "Pathology details timepoint category is {}.",
    "diagnoses[].pathology_details[].tumor_basal_diameter": "Tumor basal diameter is {} mm.",
    "diagnoses[].pathology_details[].tumor_burden": "Tumor burden is {}.",
    "diagnoses[].pathology_details[].tumor_depth_descriptor": "Tumor depth descriptor is {}.",
    "diagnoses[].pathology_details[].tumor_depth_measurement": "Tumor depth measurement is {}.",
    "diagnoses[].pathology_details[].tumor_infiltrating_lymphocytes": "Tumor-infiltrating lymphocytes are {}.",
    "diagnoses[].pathology_details[].tumor_largest_dimension_diameter": "Largest tumor dimension diameter is {} cm.",
    "diagnoses[].pathology_details[].tumor_length_measurement": "Tumor length measurement is {}.",
    "diagnoses[].pathology_details[].tumor_level_prostate": "Prostate tumor levels are {}.",
    "diagnoses[].pathology_details[].tumor_shape": "Tumor shape is {}.",
    "diagnoses[].pathology_details[].tumor_width_measurement": "Tumor width measurement is {}.",
    "diagnoses[].pathology_details[].vascular_invasion_present": "Vascular invasion present is {}.",
    "diagnoses[].pathology_details[].vascular_invasion_type": "Vascular invasion type is {}.",
    "diagnoses[].pathology_details[].zone_of_origin_prostate": "Prostate zone of origin is {}.",
    "diagnoses[].primary_diagnosis": "Primary diagnosis is {}.",
    "diagnoses[].primary_gleason_grade": "Primary Gleason grade is {}.",
    "diagnoses[].prior_malignancy": "Prior malignancy is {}.",
    "diagnoses[].prior_treatment": "Prior treatment before diagnosis is {}.",
    "diagnoses[].residual_disease": "Residual disease is {}.",
    "diagnoses[].secondary_gleason_grade": "Secondary Gleason grade is {}.",
    "diagnoses[].site_of_resection_or_biopsy": "Site of resection or biopsy is {}.",
    "diagnoses[].sites_of_involvement": "Sites of involvement are {}.",
    "diagnoses[].supratentorial_localization": "Supratentorial localization is {}.",
    "diagnoses[].synchronous_malignancy": "Synchronous malignancy is {}.",
    "diagnoses[].tissue_or_organ_of_origin": "Tissue or organ of origin is {}.",
    "diagnoses[].treatments[].chemo_concurrent_to_radiation": "Chemotherapy concurrent to radiation is {}.",
    "diagnoses[].treatments[].clinical_trial_indicator": "Clinical trial indicator is {}.",
    "diagnoses[].treatments[].initial_disease_status": "Initial disease status is {}.",
    "diagnoses[].treatments[].margin_status": "Treatment margin status is {}.",
    "diagnoses[].treatments[].number_of_cycles": "Number of treatment cycles is {}.",
    "diagnoses[].treatments[].number_of_fractions": "Number of fractions is {}.",
    "diagnoses[].treatments[].prescribed_dose": "Prescribed dose is {}.",
    "diagnoses[].treatments[].prescribed_dose_units": "Prescribed dose units are {}.",
    "diagnoses[].treatments[].pretreatment": "Pretreatment is {}.",
    "diagnoses[].treatments[].regimen_or_line_of_therapy": "Regimen or line of therapy is {}.",
    "diagnoses[].treatments[].residual_disease": "Treatment residual disease is {}.",
    "diagnoses[].treatments[].route_of_administration": "Routes of administration are {}.",
    "diagnoses[].treatments[].therapeutic_agents": "Therapeutic agents are {}.",
    "diagnoses[].treatments[].therapeutic_levels_achieved": "Therapeutic levels achieved is {}.",
    "diagnoses[].treatments[].timepoint_category": "Treatment timepoint category is {}.",
    "diagnoses[].treatments[].treatment_anatomic_sites": "Treatment anatomic sites are {}.",
    "diagnoses[].treatments[].treatment_dose": "Treatment dose is {}.",
    "diagnoses[].treatments[].treatment_dose_units": "Treatment dose units are {}.",
    "diagnoses[].treatments[].treatment_intent_type": "Treatment intent type is {}.",
    "diagnoses[].treatments[].treatment_type": "Treatment type is {}.",
    "diagnoses[].treatments[].treatment_type_administered": "Treatment type administered is {}.",
    "diagnoses[].tumor_focality": "Tumor focality is {}.",
    "diagnoses[].tumor_grade": "Tumor grade is {}.",
    "diagnoses[].tumor_grade_category": "Tumor grade category is {}.",
    "diagnoses[].ulceration_indicator": "Ulceration indicator is {}.",
    "diagnoses[].weiss_assessment_findings": "Weiss assessment findings are {}.",
    "diagnoses[].weiss_assessment_score": "Weiss assessment score is {}.",
    "exposures[].age_at_onset": "Age at exposure onset is {} years.",
    "exposures[].alcohol_days_per_week": "Alcohol days per week is {}.",
    "exposures[].alcohol_drinks_per_day": "Alcohol drinks per day is {}.",
    "exposures[].alcohol_history": "Alcohol history is {}.",
    "exposures[].alcohol_intensity": "Alcohol intensity is {}.",
    "exposures[].exposure_source": "Exposure source is {}.",
    "exposures[].occupation_type": "Occupation types are {}.",
    "exposures[].pack_years_smoked": "Pack-years smoked is {} pack-years.",
    "exposures[].tobacco_smoking_onset_year": "Tobacco smoking onset year is {}.",
    "exposures[].tobacco_smoking_quit_year": "Tobacco smoking quit year is {}.",
    "exposures[].tobacco_smoking_status": "Tobacco smoking status is {}.",
    "family_histories[].relationship_primary_diagnosis": "Relative primary diagnosis is {}.",
    "family_histories[].relationship_type": "Relationship type is {}.",
    "family_histories[].relative_with_cancer_history": "Relative with cancer history is {}.",
    "family_histories[].relatives_with_cancer_history_count": "Relatives with cancer history count is {}.",
    "follow_ups[].disease_response": "Disease response is {}.",
    "follow_ups[].ecog_performance_status": "ECOG performance status is {}.",
    "follow_ups[].evidence_of_progression_type": "Evidence of progression type is {}.",
    "follow_ups[].evidence_of_recurrence_type": "Evidence of recurrence type is {}.",
    "follow_ups[].history_of_tumor": "History of tumor is {}.",
    "follow_ups[].imaging_findings": "Imaging findings are {}.",
    "follow_ups[].imaging_result": "Imaging result is {}.",
    "follow_ups[].imaging_type": "Imaging type is {}.",
    "follow_ups[].karnofsky_performance_status": "Karnofsky performance status is {}.",
    "follow_ups[].molecular_tests[].antigen": "Antigen is {}.",
    "follow_ups[].molecular_tests[].blood_test_normal_range_lower": "Blood test normal range lower is {}.",
    "follow_ups[].molecular_tests[].blood_test_normal_range_upper": "Blood test normal range upper is {}.",
    "follow_ups[].molecular_tests[].chromosome": "Chromosome is {}.",
    "follow_ups[].molecular_tests[].chromosome_arm": "Chromosome arm is {}.",
    "follow_ups[].molecular_tests[].gene_symbol": "Gene symbol is {}.",
    "follow_ups[].molecular_tests[].laboratory_test": "Laboratory test is {}.",
    "follow_ups[].molecular_tests[].mitotic_count": "Mitotic count is {}.",
    "follow_ups[].molecular_tests[].molecular_analysis_method": "Molecular analysis method is {}.",
    "follow_ups[].molecular_tests[].second_gene_symbol": "Second gene symbol is {}.",
    "follow_ups[].molecular_tests[].staining_intensity_value": "Staining intensity value is {}.",
    "follow_ups[].molecular_tests[].test_result": "Test result is {}.",
    "follow_ups[].molecular_tests[].test_units": "Test units are {}.",
    "follow_ups[].molecular_tests[].test_value": "Test value is {}.",
    "follow_ups[].molecular_tests[].test_value_range": "Test value range is {}.",
    "follow_ups[].molecular_tests[].timepoint_category": "Molecular test timepoint category is {}.",
    "follow_ups[].molecular_tests[].variant_type": "Variant type is {}.",
    "follow_ups[].other_clinical_attributes[].bmi": "BMI is {}.",
    "follow_ups[].other_clinical_attributes[].comorbidities": "Comorbidities are {}.",
    "follow_ups[].other_clinical_attributes[].dlco_ref_predictive_percent": "DLCO percent of predicted is {}%.",
    "follow_ups[].other_clinical_attributes[].eye_color": "Eye color is {}.",
    "follow_ups[].other_clinical_attributes[].fertility_history": "Fertility history is {}.",
    "follow_ups[].other_clinical_attributes[].fev1_fvc_pre_bronch_percent": "FEV1/FVC pre-bronchodilator percent is {}%.",
    "follow_ups[].other_clinical_attributes[].fev1_ref_pre_bronch_percent": "FEV1 percent of predicted is {}%.",
    "follow_ups[].other_clinical_attributes[].height": "Height is {} cm.",
    "follow_ups[].other_clinical_attributes[].hormonal_contraceptive_use": "Hormonal contraceptive use is {}.",
    "follow_ups[].other_clinical_attributes[].hormonal_replacement_therapy_status": "Hormonal replacement therapy status is {}.",
    "follow_ups[].other_clinical_attributes[].hysterectomy_type": "Hysterectomy type is {}.",
    "follow_ups[].other_clinical_attributes[].menopause_status": "Menopause status is {}.",
    "follow_ups[].other_clinical_attributes[].number_of_pregnancies": "Number of pregnancies is {}.",
    "follow_ups[].other_clinical_attributes[].pregnancy_outcome": "Pregnancy outcome is {}.",
    "follow_ups[].other_clinical_attributes[].risk_factor_method_of_diagnosis": "Risk factor method of diagnosis is {}.",
    "follow_ups[].other_clinical_attributes[].risk_factors": "Risk factors are {}.",
    "follow_ups[].other_clinical_attributes[].timepoint_category": "Other clinical attribute timepoint category is {}.",
    "follow_ups[].other_clinical_attributes[].undescended_testis_history": "Undescended testis history is {}.",
    "follow_ups[].other_clinical_attributes[].viral_hepatitis_serology_tests": "Viral hepatitis serology tests are {}.",
    "follow_ups[].other_clinical_attributes[].weight": "Weight is {} kg.",
    "follow_ups[].peritoneal_washing_results": "Peritoneal washing result is {}.",
    "follow_ups[].timepoint_category": "Follow-up timepoint category is {}.",
    "lost_to_followup": "Lost to follow-up is {}.",
}

LABEL_OVERRIDES = {
    "bmi": "BMI",
    "icd_10_code": "ICD-10 code",
}

PLURAL_LEAVES = {
    "additional_pathology_findings",
    "ajcc_serum_tumor_markers",
    "ann_arbor_b_symptoms",
    "comorbidities",
    "imaging_findings",
    "occupation_type",
    "peritoneal_washing_results",
    "risk_factors",
    "route_of_administration",
    "sites_of_involvement",
    "test_units",
    "treatment_anatomic_sites",
    "treatment_dose_units",
    "tumor_level_prostate",
    "viral_hepatitis_serology_tests",
    "weiss_assessment_findings",
}

ACRONYM_TOKENS = {
    "ajcc",
    "bmi",
    "calgb",
    "dlco",
    "ecog",
    "ensat",
    "fab",
    "fev1",
    "figo",
    "fvc",
    "icd",
    "prcc",
}


def _clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return text


def field_leaf(field: str) -> str:
    return str(field).split(".")[-1].replace("[]", "")


def mapping_field_to_prompt_path(field: str) -> str:
    return ".".join(ARRAY_PREFIX.get(part, part) for part in str(field).split("."))


def _gdc_type_tokens(type_text: str) -> set[str]:
    tokens = set()
    for raw in re.split(r"[|]", _clean_text(type_text).lower()):
        token = raw.strip()
        if token and token != "null":
            tokens.add(token)
    return tokens


def _is_integer_type(type_text: str) -> bool:
    return "integer" in _gdc_type_tokens(type_text)


def _is_numeric_type(type_text: str) -> bool:
    return bool(_gdc_type_tokens(type_text) & {"integer", "number"})


def _unit_from_description(field: str, description: str, type_text: str) -> str:
    if field in UNIT_OVERRIDES:
        return UNIT_OVERRIDES[field]
    if not _is_numeric_type(type_text):
        return ""
    text = _clean_text(description)
    if not text:
        return ""
    lowered = text.lower()
    if re.search(r"calendar year|year in which|year that the patient|year of the patient's last follow-up", lowered):
        return ""
    if re.search(r"\b(in years|age \(in years\)|duration, in years|number of years)\b", lowered):
        return "years"
    if re.search(r"\bcentimeters\b", lowered):
        return "cm"
    if re.search(r"\bmillimeters\b|\(mm\)", lowered):
        return "mm"
    if re.search(r"\bkilograms\b", lowered):
        return "kg"
    if re.search(r"\bgrams\b", lowered):
        return "g"
    if "percent" in lowered or "percentage" in lowered:
        return "%"
    if "hours per day" in lowered:
        return "hours/day"
    if "milligrams per milliliter" in lowered:
        return "mg/mL"
    if re.search(r"number of days during which|number of days a patient", lowered):
        return "days"
    if re.search(r"\bnumber of weeks\b", lowered):
        return "weeks"
    return ""


def load_official_field_meta(
    mapping_csv: Path | None = None,
    dictionary_csv: Path | None = None,
) -> dict[str, dict[str, str]]:
    global _OFFICIAL_META
    use_cache = mapping_csv is None and dictionary_csv is None
    if use_cache and _OFFICIAL_META is not None:
        return _OFFICIAL_META
    mapping_path = Path(mapping_csv or DEFAULT_GDC_CASES_MAPPING)
    dict_path = Path(dictionary_csv or DEFAULT_GDC_CLINICAL_DICTIONARY)
    csv.field_size_limit(10_000_000)
    with mapping_path.open("r", encoding="utf-8-sig", newline="") as handle:
        mapping_rows = list(csv.DictReader(handle))
    with dict_path.open("r", encoding="utf-8-sig", newline="") as handle:
        dict_rows = list(csv.DictReader(handle))
    by_entity_field = {
        (_clean_text(row.get("entity")), _clean_text(row.get("field"))): row
        for row in dict_rows
    }
    meta: dict[str, dict[str, str]] = {}
    for row in mapping_rows:
        mapping_field = _clean_text(row.get("field"))
        entity = _clean_text(row.get("entity"))
        prompt_field = mapping_field_to_prompt_path(mapping_field)
        leaf = field_leaf(prompt_field)
        dict_row = by_entity_field.get((entity, leaf))
        if dict_row is None:
            dict_row = {
                "type": _clean_text(row.get("type")),
                "description": _clean_text(row.get("description")),
            }
        if prompt_field in meta:
            raise ValueError(f"duplicate prompt field {prompt_field}")
        meta[prompt_field] = {
            "entity": entity,
            "mapping_field": mapping_field,
            "type": _clean_text(dict_row.get("type")),
            "description": _clean_text(dict_row.get("description")),
        }
    if use_cache:
        _OFFICIAL_META = meta
    return meta


def load_official_prompt_fields(
    mapping_csv: Path | None = None,
    dictionary_csv: Path | None = None,
    rules: dict | None = None,
) -> list[str]:
    meta = load_official_field_meta(mapping_csv, dictionary_csv)
    rules = rules or load_filter_rules()
    fields = []
    for field in meta:
        fake = pd.Series(
            {
                "field_path": field,
                "coverage": 1.0,
                "unique_count": 10,
                "mode_share": 0.1,
            }
        )
        rule, _ = apply_rules(
            fake,
            min_coverage=0.0,
            min_unique=0,
            max_mode_share=1.0,
            rules=rules,
        )
        if rule is None:
            fields.append(field)
    return fields


def _existing_spec_templates(path: Path | None = None) -> dict[str, str]:
    path = Path(path or SHARED_SPEC_PATH)
    global _EXISTING_TEMPLATES
    if path == SHARED_SPEC_PATH and _EXISTING_TEMPLATES is not None:
        return _EXISTING_TEMPLATES
    if not path.exists():
        return {}
    templates = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            field = _clean_text(raw.get("field"))
            template = _clean_text(raw.get("template"))
            if field and template:
                templates[field] = template
    if path == SHARED_SPEC_PATH:
        _EXISTING_TEMPLATES = templates
    return templates


def field_convert(field: str) -> str:
    if field in DAYS_TO_YEARS_FIELDS:
        return "days_to_years"
    meta = load_official_field_meta().get(field)
    if meta and _is_integer_type(meta["type"]):
        return "int"
    return ""


def field_unit(field: str) -> str:
    if field in DAYS_TO_YEARS_FIELDS:
        return "years"
    meta = load_official_field_meta().get(field, {})
    return _unit_from_description(field, meta.get("description", ""), meta.get("type", ""))


def field_label(field: str) -> str:
    leaf = field_leaf(field)
    if leaf in LABEL_OVERRIDES:
        return LABEL_OVERRIDES[leaf]
    pretty = []
    for tok in leaf.split("_"):
        low = tok.lower()
        if low == "fev1":
            pretty.append("FEV1")
        elif low in ACRONYM_TOKENS:
            pretty.append(tok.upper())
        else:
            pretty.append(tok.replace("-", " ").capitalize())
    label = " ".join(pretty)
    label = label.replace("Icd 10", "ICD-10")
    return label


def default_template(field: str) -> str:
    existing = _existing_spec_templates().get(field)
    if existing:
        return existing
    if field in TEMPLATE_OVERRIDES:
        return TEMPLATE_OVERRIDES[field]
    leaf = field_leaf(field)
    label = field_label(field)
    unit = field_unit(field)
    if leaf in PLURAL_LEAVES or leaf.endswith("_sites") or leaf.endswith("_tests") or leaf.endswith("_findings"):
        if unit:
            return f"{label} are {{}} {unit}."
        return f"{label} are {{}}."
    if unit:
        return f"{label} is {{}} {unit}."
    return f"{label} is {{}}."


def spec_row(field: str) -> dict[str, str]:
    convert = field_convert(field)
    unit = field_unit(field)
    template = default_template(field)
    notes = []
    if convert == "days_to_years":
        notes.append("GDC stores age as days since birth")
    elif convert == "int":
        notes.append("strip trailing .0")
    if unit:
        notes.append(f"unit from GDC description: {unit}")
    if field in TEMPLATE_OVERRIDES or field in _existing_spec_templates():
        notes.append("canonical sentence")
    return {
        "field": field,
        "convert": convert,
        "unit": unit,
        "template": template,
        "note": "; ".join(notes),
    }


def validate_spec_row(row: dict[str, str]) -> None:
    field = _clean_text(row.get("field"))
    convert = _clean_text(row.get("convert"))
    template = _clean_text(row.get("template"))
    if not field:
        raise ValueError("shared spec row missing field")
    known = {name.lower() for name in known_converters()}
    if convert.lower() not in known:
        raise ValueError(f"unsupported convert {convert!r} for {field}")
    if template.count("{}") != 1:
        raise ValueError(f"template for {field} must contain exactly one {{}}: {template!r}")
    if not template.endswith("."):
        raise ValueError(f"template for {field} must end with a period: {template!r}")


def load_shared_spec(path: Path | None = None) -> dict[str, dict[str, str]]:
    path = Path(path or SHARED_SPEC_PATH)
    if not path.exists():
        raise FileNotFoundError(f"shared Field Bank spec not found: {path}")
    spec = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [col for col in SPEC_COLUMNS if col not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"shared spec missing columns {missing}: {path}")
        for raw in reader:
            row = {key: _clean_text(raw.get(key, "")) for key in SPEC_COLUMNS}
            validate_spec_row(row)
            field = row["field"]
            if field in spec:
                raise ValueError(f"duplicate shared spec field: {field}")
            spec[field] = row
    return spec


def write_shared_spec(fields: list[str] | None = None, path: Path | None = None) -> Path:
    path = Path(path or SHARED_SPEC_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = load_official_prompt_fields()
    rows = [spec_row(field) for field in sorted(set(fields))]
    for row in rows:
        validate_spec_row(row)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SPEC_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    global _EXISTING_TEMPLATES
    if path == SHARED_SPEC_PATH:
        _EXISTING_TEMPLATES = {row["field"]: row["template"] for row in rows}
    return path


def fill_from_spec(
    field: str,
    current: dict[str, str] | None = None,
    spec: dict[str, dict[str, str]] | None = None,
    *,
    overwrite_convert_unit: bool = True,
    overwrite_template: bool = False,
) -> dict[str, str]:
    current = current or {}
    spec = spec or {}
    rule = spec.get(field) or spec_row(field)
    convert = _clean_text(current.get("convert"))
    unit = _clean_text(current.get("unit"))
    template = _clean_text(current.get("template"))
    if overwrite_convert_unit or not convert:
        convert = rule["convert"]
    if overwrite_convert_unit or not unit:
        unit = rule["unit"]
    if overwrite_template or not template:
        template = rule["template"]
    return {
        "convert": convert,
        "unit": unit,
        "template": template,
    }
