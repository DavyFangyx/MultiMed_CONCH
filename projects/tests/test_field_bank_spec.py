from pathlib import Path
import sys

import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from discovery.field_bank import TEMPLATE_COLUMNS, write_field_bank_template_skeleton
from discovery.field_bank_spec import (
    SHARED_SPEC_PATH,
    field_convert,
    load_shared_spec,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIELD_BANK_ROOT = PROJECT_ROOT / "templates" / "field_bank"
LIHC_PATH = FIELD_BANK_ROOT / "TCGA_LIHC" / "FIELD_BANK.csv"

LIHC_TEMPLATES = {
    "demographic.country_of_residence_at_enrollment": "Country of residence at enrollment is {}.",
    "demographic.ethnicity": "Ethnicity is {}.",
    "demographic.race": "Race is {}.",
    "demographic.sex_at_birth": "Sex at birth is {}.",
    "diagnoses[].age_at_diagnosis": "Age at diagnosis is {} years.",
    "diagnoses[].ajcc_pathologic_m": "Pathologic M stage is {}.",
    "diagnoses[].ajcc_pathologic_n": "Pathologic N stage is {}.",
    "diagnoses[].ajcc_pathologic_t": "Pathologic T stage is {}.",
    "diagnoses[].child_pugh_classification": "Child-Pugh classification is {}.",
    "diagnoses[].diagnosis_is_primary_disease": "The diagnosis is the primary disease: {}.",
    "diagnoses[].ishak_fibrosis_score": "Ishak fibrosis score is {}.",
    "diagnoses[].morphology": "Tumor morphology is {}.",
    "diagnoses[].pathology_details[].vascular_invasion_present": "Vascular invasion present is {}.",
    "diagnoses[].pathology_details[].vascular_invasion_type": "Vascular invasion type is {}.",
    "diagnoses[].primary_diagnosis": "Primary diagnosis is {}.",
    "diagnoses[].prior_malignancy": "Prior malignancy is {}.",
    "diagnoses[].prior_treatment": "Prior treatment before diagnosis is {}.",
    "diagnoses[].residual_disease": "Residual disease is {}.",
    "diagnoses[].tissue_or_organ_of_origin": "Tissue or organ of origin is {}.",
    "diagnoses[].treatments[].initial_disease_status": "Initial disease status is {}.",
    "diagnoses[].treatments[].treatment_anatomic_sites": "Treatment anatomic sites are {}.",
    "diagnoses[].treatments[].treatment_type": "Treatment type is {}.",
    "diagnoses[].tumor_grade": "Tumor grade is {}.",
    "family_histories[].relative_with_cancer_history": "Relative with cancer history is {}.",
    "follow_ups[].disease_response": "Disease response is {}.",
    "follow_ups[].ecog_performance_status": "ECOG performance status is {}.",
    "follow_ups[].molecular_tests[].blood_test_normal_range_lower": "Blood test normal range lower is {}.",
    "follow_ups[].molecular_tests[].blood_test_normal_range_upper": "Blood test normal range upper is {}.",
    "follow_ups[].molecular_tests[].laboratory_test": "Laboratory test is {}.",
    "follow_ups[].molecular_tests[].test_units": "Test units are {}.",
    "follow_ups[].molecular_tests[].test_value": "Test value is {}.",
    "follow_ups[].other_clinical_attributes[].bmi": "BMI is {}.",
    "follow_ups[].other_clinical_attributes[].height": "Height is {} cm.",
    "follow_ups[].other_clinical_attributes[].risk_factors": "Risk factors are {}.",
    "follow_ups[].other_clinical_attributes[].timepoint_category": "Other clinical attribute timepoint category is {}.",
    "follow_ups[].other_clinical_attributes[].viral_hepatitis_serology_tests": "Viral hepatitis serology tests are {}.",
    "follow_ups[].other_clinical_attributes[].weight": "Weight is {} kg.",
    "follow_ups[].timepoint_category": "Follow-up timepoint category is {}.",
    "lost_to_followup": "Lost to follow-up is {}.",
}

ALLOWED_CONVERT = {"", "days_to_years", "int"}


def _dataset_tables():
    return sorted(
        path
        for path in FIELD_BANK_ROOT.glob("*/FIELD_BANK.csv")
        if path.parent.name != "_shared"
    )


def _all_fields():
    fields = set()
    for path in _dataset_tables():
        df = pd.read_csv(path)
        fields.update(str(value) for value in df["field"].tolist())
    return fields


def test_shared_spec_covers_all_kept_fields():
    fields = _all_fields()
    spec = load_shared_spec()
    assert set(spec) == fields
    assert len(spec) == 194


def test_convert_and_unit_are_shared():
    spec = load_shared_spec()
    seen = {}
    for path in _dataset_tables():
        df = pd.read_csv(path)
        for row in df.itertuples(index=False):
            field = str(row.field)
            convert = "" if pd.isna(row.convert) else str(row.convert)
            unit = "" if pd.isna(row.unit) else str(row.unit)
            template = "" if pd.isna(row.template) else str(row.template)
            assert convert in ALLOWED_CONVERT, field
            assert template.count("{}") == 1, field
            assert template.endswith("."), field
            key = (convert, unit)
            if field not in seen:
                seen[field] = key
            assert seen[field] == key, field
            assert spec[field]["convert"] == convert, field
            assert spec[field]["unit"] == unit, field
    assert not df.empty


def test_templates_are_complete_and_lihc_preserved():
    empty = []
    for path in _dataset_tables():
        df = pd.read_csv(path)
        blank = df["template"].isna() | (df["template"].astype(str).str.strip() == "") | (df["template"].astype(str).str.lower() == "nan")
        empty.extend(f"{path.parent.name}:{field}" for field in df.loc[blank, "field"].tolist())
    assert empty == []
    lihc = pd.read_csv(LIHC_PATH)
    got = dict(zip(lihc["field"], lihc["template"]))
    assert got == LIHC_TEMPLATES


def test_age_at_diagnosis_uses_days_to_years():
    assert field_convert("diagnoses[].age_at_diagnosis") == "days_to_years"
    for path in _dataset_tables():
        df = pd.read_csv(path)
        sub = df[df["field"] == "diagnoses[].age_at_diagnosis"]
        if sub.empty:
            continue
        row = sub.iloc[0]
        assert row["convert"] == "days_to_years"
        assert row["unit"] == "years"
        assert row["template"] == "Age at diagnosis is {} years."


def test_write_templates_preserves_filled_rows(tmp_path):
    out_dir = tmp_path / "TCGA-CESC"
    out_dir.mkdir()
    existing = pd.DataFrame(
        [
            {
                "field": "diagnoses[].age_at_diagnosis",
                "example": "8900.0",
                "convert": "days_to_years",
                "unit": "years",
                "template": "Age at diagnosis is {} years.",
            },
            {
                "field": "demographic.race",
                "example": "white",
                "convert": "",
                "unit": "",
                "template": "Race is {}.",
            },
        ],
        columns=TEMPLATE_COLUMNS,
    )
    existing.to_csv(out_dir / "FIELD_BANK.csv", index=False)
    write_field_bank_template_skeleton(
        "TCGA-CESC",
        [
            "diagnoses[].age_at_diagnosis",
            "demographic.race",
            "diagnoses[].figo_stage",
        ],
        out_dir=out_dir,
        examples={"diagnoses[].figo_stage": "Stage I"},
    )
    df = pd.read_csv(out_dir / "FIELD_BANK.csv").fillna("")
    by_field = {row.field: row for row in df.itertuples(index=False)}
    assert by_field["diagnoses[].age_at_diagnosis"].convert == "days_to_years"
    assert by_field["diagnoses[].age_at_diagnosis"].unit == "years"
    assert by_field["diagnoses[].age_at_diagnosis"].template == "Age at diagnosis is {} years."
    assert by_field["diagnoses[].age_at_diagnosis"].example == "8900.0"
    assert by_field["demographic.race"].template == "Race is {}."
    assert by_field["diagnoses[].figo_stage"].template == "FIGO stage is {}."
    assert by_field["diagnoses[].figo_stage"].example == "Stage I"


if __name__ == "__main__":
    import tempfile
    test_shared_spec_covers_all_kept_fields()
    test_convert_and_unit_are_shared()
    test_templates_are_complete_and_lihc_preserved()
    test_age_at_diagnosis_uses_days_to_years()
    with tempfile.TemporaryDirectory() as tmp:
        test_write_templates_preserves_filled_rows(Path(tmp))
    print("ok")
