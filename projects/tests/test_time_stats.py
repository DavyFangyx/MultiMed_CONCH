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
    assert row["diagnoses_treatments_record1"] == 10
    assert row["diagnoses_treatments_record2"] == 0  # Preoperative inherits parent diagnosis
    assert row["diagnoses_treatments_record3"] in ("", None) or pd.isna(row["diagnoses_treatments_record3"])
    assert row["diagnoses_pathology_details_record1"] == 2
    assert row["diagnoses_pathology_details_record2"] == 0  # Initial Diagnosis inherits parent
    assert row["follow_ups_record1"] == 80
    assert row["follow_ups_record2"] in ("", None) or pd.isna(row["follow_ups_record2"])
    assert row["follow_ups_molecular_tests_record1"] == 70
    assert row["follow_ups_molecular_tests_record2"] == 80  # inherit parent follow-up
    assert row["follow_ups_other_clinical_attributes_record1"] == 75  # comorbidity over risk_factor
    assert row["follow_ups_other_clinical_attributes_record2"] == 80


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
    assert float(rec.loc[0, "diagnoses_treatments_record1"]) == round(10 / 120, 6)
    assert float(rec.loc[0, "follow_ups_other_clinical_attributes_record1"]) == round(75 / 120, 6)


def test_missing_slot_denominator_is_object_presence():
    records, _, _ = _frames()
    write_missing = build_missing_tables(records, WRITE_KIND)
    record_missing = build_missing_tables(records, RECORD_KIND)
    treat_write = write_missing["diagnoses_treatments"]
    treat_record = record_missing["diagnoses_treatments"]
    assert list(treat_write["ratio"])[:3] == ["2/2", "1/1", "0/1"]
    assert list(treat_record["ratio"])[:3] == ["2/2", "1/1", "0/1"]
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
    assert record_df.loc[0, "follow_ups_molecular_tests_record1"] == 12
    assert str(write_df.loc[0, "follow_ups_updated1"]).startswith("2024-04-01")
    assert str(write_df.loc[0, "follow_ups_updated2"]).startswith("2024-05-01")
    missing = build_missing_tables(records, RECORD_KIND)["follow_ups"]
    assert list(missing["path"]) == ["follow_ups[1]", "follow_ups[2]"]
    assert list(missing["ratio"]) == ["1/1", "0/1"]
    write_missing = build_missing_tables(records, WRITE_KIND)["follow_ups"]
    assert list(write_missing["ratio"]) == ["1/1", "1/1"]

