from pathlib import Path
import sys

import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from time_stats import (
    RECORD_KIND,
    WRITE_KIND,
    _expand_kind_columns,
    _synthetic_cases,
    build_missing_tables,
    build_normalized_record_frame,
    build_normalized_write_frame,
    extract_patient_time_record,
)


def _frames():
    records = [extract_patient_time_record(case, dataset_name="synthetic") for case in _synthetic_cases()]
    write_df = pd.DataFrame(_expand_kind_columns(records, WRITE_KIND))
    record_df = pd.DataFrame(_expand_kind_columns(records, RECORD_KIND))
    return records, write_df, record_df


def test_survival_endpoint_unchanged():
    _, write_df, record_df = _frames()
    assert write_df.loc[0, "ground_truth_time"] == 120
    assert write_df.loc[0, "event"] == 0
    assert write_df.loc[1, "ground_truth_time"] == 45
    assert write_df.loc[1, "event"] == 1
    assert record_df.loc[0, "ground_truth_source"] == "diagnoses.days_to_last_follow_up"
    assert record_df.loc[1, "ground_truth_source"] == "demographic.days_to_death"


def test_ignored_entities_are_absent():
    _, write_df, record_df = _frames()
    joined = " ".join(map(str, list(write_df.columns) + list(record_df.columns)))
    for token in ("exposures", "family_histories", "demographic_updated", "updated_datetime"):
        assert token not in joined
    assert "diagnoses_updated1" in write_df.columns
    assert "diagnoses_record1" in record_df.columns


def test_record_primary_and_narrow_table_fallback():
    _, _, record_df = _frames()
    row = record_df.loc[0]
    assert row["diagnoses_record1"] == 0
    assert row["diagnoses_treatments_record1"] == 80  # t_hi via H1b follow-up
    assert row["diagnoses_treatments_record2"] in ("", None) or pd.isna(row["diagnoses_treatments_record2"])  # timepoint-only stays unlocalized
    assert row["diagnoses_treatments_record3"] in ("", None) or pd.isna(row["diagnoses_treatments_record3"])
    assert row["diagnoses_treatments_record4"] in ("", None) or pd.isna(row["diagnoses_treatments_record4"])
    assert "diagnoses_treatments_record5" not in record_df.columns  # treatment_or_therapy=no is skipped
    assert row["diagnoses_pathology_details_record1"] in ("", None) or pd.isna(row["diagnoses_pathology_details_record1"])  # P3, ignore days_to_pathology_detail
    assert row["diagnoses_pathology_details_record2"] in ("", None) or pd.isna(row["diagnoses_pathology_details_record2"])
    assert row["follow_ups_record1"] == 80
    assert row["follow_ups_record2"] in ("", None) or pd.isna(row["follow_ups_record2"])
    assert row["follow_ups_molecular_tests_record1"] == 80
    assert row["follow_ups_molecular_tests_record2"] in ("", None) or pd.isna(row["follow_ups_molecular_tests_record2"])
    assert row["follow_ups_other_clinical_attributes_record1"] == 80  # positive comorbidity day is t_lo; t_hi via H1b
    assert row["follow_ups_other_clinical_attributes_record2"] in ("", None) or pd.isna(row["follow_ups_other_clinical_attributes_record2"])


def test_write_uses_object_updated_datetime_only():
    _, write_df, _ = _frames()
    row = write_df.loc[0]
    assert str(row["diagnoses_updated1"]).startswith("2024-03-01")
    assert str(row["diagnoses_treatments_updated2"]).startswith("2024-03-03")
    assert row["diagnoses_treatments_updated3"] in ("", None) or pd.isna(row["diagnoses_treatments_updated3"])


def test_normalized_write_and_record():
    _, write_df, record_df = _frames()
    wide = build_normalized_write_frame(write_df)
    rec = build_normalized_record_frame(record_df)
    assert float(wide.loc[0, "last_time_days"]) == 120
    assert float(wide.loc[0, "follow_ups_updated2"]) > 1.0
    assert float(rec.loc[0, "diagnoses_treatments_record1"]) == round(80 / 120, 6)
    assert float(rec.loc[0, "follow_ups_other_clinical_attributes_record1"]) == round(80 / 120, 6)


def test_missing_slot_denominator_is_object_presence():
    records, _, _ = _frames()
    write_missing = build_missing_tables(records, WRITE_KIND)
    record_missing = build_missing_tables(records, RECORD_KIND)
    treat_write = write_missing["diagnoses_treatments"]
    treat_record = record_missing["diagnoses_treatments"]
    assert list(treat_write["ratio"])[:3] == ["2/2", "1/1", "0/1"]
    assert list(treat_record["ratio"])[:4] == ["2/2", "0/1", "0/1", "0/1"]
    assert list(treat_record["point"])[:4] == [0, 0, 0, 0]
    assert list(treat_record["bounded"])[:4] == [2, 0, 0, 0]
    assert list(treat_record["lo_only"])[:4] == [0, 0, 0, 0]
    assert list(treat_record["unlocated"])[:4] == [0, 1, 1, 1]
    follow_record = record_missing["follow_ups"]
    assert follow_record.loc[0, "ratio"] == "2/2"
    assert follow_record.loc[1, "ratio"] == "0/1"
    assert follow_record.loc[1, "path"] == "follow_ups[2]"
    patho = record_missing["diagnoses_pathology_details"]
    assert patho.loc[0, "path"] == "diagnoses[].pathology_details[1]"


def test_follow_up_shells_are_skipped():
    case = {
        "submitter_id": "TCGA-AA-0003",
        "case_id": "uuid-3",
        "demographic": {"vital_status": "Alive"},
        "diagnoses": [{"days_to_diagnosis": 0, "days_to_last_follow_up": 100}],
        "follow_ups": [
            {
                "days_to_follow_up": 80,
                "submitter_id": "TCGA-AA-0003_follow_up",
                "updated_datetime": "2024-04-01T00:00:00-06:00",
            },
            {
                "follow_up_id": "shell-mt",
                "molecular_tests": [
                    {"days_to_test": 12, "updated_datetime": "2024-04-02T00:00:00-06:00"}
                ],
            },
            {
                "ecog_performance_status": 1,
                "updated_datetime": "2024-05-01T00:00:00-06:00",
            },
            {
                "follow_up_id": "shell-oca",
                "other_clinical_attributes": [{"timepoint_category": "Initial Diagnosis"}],
            },
        ],
    }
    records = [extract_patient_time_record(case, dataset_name="synthetic")]
    write_df = pd.DataFrame(_expand_kind_columns(records, WRITE_KIND))
    record_df = pd.DataFrame(_expand_kind_columns(records, RECORD_KIND))
    slots = records[0]["_slots"]["follow_ups"]
    assert len(slots) == 2
    assert record_df.loc[0, "follow_ups_record1"] == 80
    assert record_df.loc[0, "follow_ups_record2"] in ("", None) or pd.isna(record_df.loc[0, "follow_ups_record2"])
    assert "follow_ups_record3" not in record_df.columns
    assert record_df.loc[0, "follow_ups_molecular_tests_record1"] == 80
    assert str(write_df.loc[0, "follow_ups_updated1"]).startswith("2024-04-01")
    assert str(write_df.loc[0, "follow_ups_updated2"]).startswith("2024-05-01")
    missing = build_missing_tables(records, RECORD_KIND)["follow_ups"]
    assert list(missing["path"]) == ["follow_ups[1]", "follow_ups[2]"]
    assert list(missing["ratio"]) == ["1/1", "0/1"]
    write_missing = build_missing_tables(records, WRITE_KIND)["follow_ups"]
    assert list(write_missing["ratio"]) == ["1/1", "1/1"]


def test_treatment_locked_exception_and_unlocalized():
    case = {
        "submitter_id": "TCGA-AA-0004",
        "case_id": "uuid-4",
        "demographic": {"vital_status": "Alive"},
        "diagnoses": [
            {
                "days_to_diagnosis": 0,
                "days_to_last_follow_up": 100,
                "treatments": [
                    {"days_to_treatment_start": 12},
                    {"timepoint_category": "Preoperative"},
                    {"treatment_or_therapy": "yes"},
                    {"treatment_or_therapy": "no"},
                    {"treatment_or_therapy": "unknown"},
                    {"treatment_or_therapy": "no", "timepoint_category": "Initial Diagnosis"},
                ],
                "pathology_details": [
                    {"timepoint_category": "Initial Diagnosis"},
                    {"days_to_pathology_detail": 4},
                    {},
                ],
            },
            {
                "days_to_diagnosis": -10,
                "c": [
                    {
                        "treatment_intent_type": None,
                        "treatment_type": "Pharmaceutical Therapy, NOS",
                        "treatment_or_therapy": "no",
                    }
                ],
            },
            {
                "c": [
                    {"treatment_or_therapy": "no", "treatment_type": "Radiation Therapy, NOS"},
                ],
            },
        ],
    }
    records = [extract_patient_time_record(case, dataset_name="synthetic")]
    treatments = records[0]["_slots"]["diagnoses_treatments"]
    pathology = records[0]["_slots"]["diagnoses_pathology_details"]
    assert treatments[0]["obj"]["days_to_treatment_start"] == 12
    assert [slot["record_days"] for slot in treatments] == [100, None, None, None]
    assert [slot["record_status"] for slot in treatments] == [
        "bounded",
        "unlocated",
        "unlocated",
        "unlocated",
    ]
    assert all(slot["obj"].get("treatment_or_therapy") != "no" for slot in treatments)
    assert [slot["record_days"] for slot in pathology] == [None, None, None]
    missing = build_missing_tables(records, RECORD_KIND)["diagnoses_treatments"]
    assert list(missing["ratio"])[:4] == ["1/1", "0/1", "0/1", "0/1"]
    assert list(missing["point"])[:4] == [0, 0, 0, 0]
    assert list(missing["bounded"])[:4] == [1, 0, 0, 0]
    assert list(missing["lo_only"])[:4] == [0, 0, 0, 0]
    assert list(missing["unlocated"])[:4] == [0, 1, 1, 1]

