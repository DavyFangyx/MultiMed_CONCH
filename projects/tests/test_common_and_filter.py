from pathlib import Path
import json
import sys

import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common.fields import extract_path_values, get_primary_diagnosis
from common.missingness import classify_raw_value
from common.types import infer_type
from discovery.filter import apply_rules, timepoint
from schemes.config import load_custom_schemes, reset_scheme_registry, resolve_scheme_names


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


def test_scheme_loader_skips_field_bank(tmp_path):
    cfg = {
        "L0": {
            "template_file": "L0_template.csv",
            "prompt_file": "prompts.csv",
            "dirname": "L0",
            "template_cols": ["AGE_TEMPLATE"],
            "placeholders": ["AGE"],
            "output_cols": ["age_template"],
        },
        "FIELD_BANK": {
            "template_file": "x.csv",
            "prompt_file": "y.csv",
            "dirname": "FIELD_BANK",
            "template_cols": ["AGE_TEMPLATE"],
            "placeholders": ["AGE"],
            "output_cols": ["age_template"],
        },
    }
    path = tmp_path / "schemes.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    reset_scheme_registry()
    load_custom_schemes(str(tmp_path))
    assert resolve_scheme_names("all") == ["L0"]
    try:
        resolve_scheme_names("FIELD_BANK")
        assert False, "FIELD_BANK should raise"
    except ValueError as exc:
        assert "run_field_bank.py" in str(exc)




if __name__ == "__main__":
    test_extract_path_and_primary_diagnosis()
    test_missingness_three_state()
    test_filter_rules()
    test_infer_type_stage_vs_class()
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        test_scheme_loader_skips_field_bank(Path(tmp))
    print("ok")
