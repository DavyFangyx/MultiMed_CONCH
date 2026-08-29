from pathlib import Path
import sys

import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common.fields import extract_path_values, get_primary_diagnosis
from common.missingness import classify_raw_value
from common.paths import PROJECT_ROOT, dataset_field_bank_dir, dataset_greedy_dir, validate_encoding
from common.types import infer_type
from discovery.cli import build_field_bank_parser, field_bank_main
from discovery.filter import apply_rules, timepoint


def _case():
    return {
        "submitter_id": "TCGA-XX-0001",
        "demographic": {"age_at_index": 61, "race": "not reported"},
        "diagnoses": [
            {
                "diagnosis_is_primary_disease": "true",
                "primary_diagnosis": "Adenocarcinoma",
                "ajcc_pathologic_t": "T2",
            }
        ],
        "follow_ups": [{"ecog_performance_status": "1"}],
    }


def test_extract_path_and_primary_diagnosis():
    case = _case()
    assert extract_path_values(case, "demographic.age_at_index") == [61]
    assert get_primary_diagnosis(case["diagnoses"])["primary_diagnosis"] == "Adenocarcinoma"


def test_missingness_three_state():
    assert classify_raw_value(None) == "null"
    assert classify_raw_value("") == "null"
    assert classify_raw_value("not reported") == "sentinel"
    assert classify_raw_value("white") == "valid"


def test_filter_rules():
    leak = pd.Series(
        {
            "field_path": "demographic.vital_status",
            "coverage": 0.9,
            "unique_count": 2,
            "mode_share": 0.5,
        }
    )
    rule, _ = apply_rules(leak, min_coverage=0.3)
    assert rule == "R0_label_leak"

    id_row = pd.Series(
        {
            "field_path": "case_id",
            "coverage": 1.0,
            "unique_count": 10,
            "mode_share": 0.1,
        }
    )
    rule, _ = apply_rules(id_row, min_coverage=0.3)
    assert rule == "R1_admin"

    keep = pd.Series(
        {
            "field_path": "diagnoses[].ajcc_pathologic_t",
            "coverage": 0.8,
            "unique_count": 5,
            "mode_share": 0.4,
        }
    )
    rule, _ = apply_rules(keep, min_coverage=0.3)
    assert rule is None
    assert timepoint("follow_ups[].ecog_performance_status") == "follow_up"
    assert timepoint("diagnoses[].ajcc_pathologic_t") == "baseline"


def test_infer_type_stage_vs_class():
    assert infer_type("ajcc_pathologic_t", ["T1", "T2", "T3", "T4"], 4) == "ordinal_stage"
    assert infer_type("ajcc_clinical_stage", ["Stage I", "Stage II", "Stage IIIA"], 3) == "ordinal_stage"
    assert infer_type("race", ["white", "black", "asian"], 3) == "ordinal_class"
    assert infer_type("gender", ["male", "female"], 2) == "ordinal_class"
    assert infer_type("icd_10_code", ["C18.2", "C18.7", "C20"], 3) == "ordinal_class"
    assert infer_type("age_at_diagnosis", [61, 62, 70], 3) == "numeric"


def test_dataset_field_bank_dir_defaults_to_prompt():
    assert dataset_field_bank_dir("TCGA-BRCA") == PROJECT_ROOT / "outputs" / "TCGA-BRCA" / "field_bank" / "prompt"


def test_dataset_field_bank_dir_onehot():
    assert dataset_field_bank_dir("TCGA-BRCA", "onehot") == PROJECT_ROOT / "outputs" / "TCGA-BRCA" / "field_bank" / "onehot"


def test_dataset_greedy_dir_onehot():
    assert dataset_greedy_dir("TCGA-BRCA", "onehot") == PROJECT_ROOT / "outputs" / "TCGA-BRCA" / "greedy" / "onehot"


def test_invalid_encoding_raises():
    with pytest.raises(ValueError, match="unsupported encoding"):
        validate_encoding("hash")
    with pytest.raises(ValueError, match="unsupported encoding"):
        dataset_field_bank_dir("TCGA-BRCA", "hash")
    with pytest.raises(ValueError, match="unsupported encoding"):
        dataset_greedy_dir("TCGA-BRCA", "hash")


def test_field_bank_main_rejects_unknown_encoding():
    parser = build_field_bank_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--dataset", "TCGA-BRCA", "--encoding", "hash"])
    with pytest.raises(SystemExit):
        field_bank_main(["--dataset", "TCGA-BRCA", "--encoding", "hash"])


if __name__ == "__main__":
    test_extract_path_and_primary_diagnosis()
    test_missingness_three_state()
    test_filter_rules()
    test_infer_type_stage_vs_class()
    test_dataset_field_bank_dir_defaults_to_prompt()
    test_dataset_field_bank_dir_onehot()
    test_dataset_greedy_dir_onehot()
    test_invalid_encoding_raises()
    test_field_bank_main_rejects_unknown_encoding()
    print("ok")
