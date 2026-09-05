from pathlib import Path
import sys
import tempfile

import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common.fields import extract_path_values, get_primary_diagnosis
from common.missingness import classify_raw_value
from common.paths import PROJECT_ROOT, dataset_field_bank_dir, dataset_greedy_dir, dataset_linear_probe_dir, dataset_univariate_dir, normalize_experiment, validate_encoding
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


def test_filter_rules_new_r0_r1_and_thresholds():
    lost = pd.Series(
        {
            "field_path": "lost_to_followup",
            "coverage": 0.9,
            "unique_count": 2,
            "mode_share": 0.5,
        }
    )
    rule, _ = apply_rules(lost)
    assert rule == "R0_label_leak"

    follow_up = pd.Series(
        {
            "field_path": "follow_ups[].ecog_performance_status",
            "coverage": 0.99,
            "unique_count": 2,
            "mode_share": 0.6,
        }
    )
    rule, _ = apply_rules(follow_up)
    assert rule is None
    rule, trigger = apply_rules(follow_up, no_landmark=True)
    assert rule == "R0_label_leak"
    assert trigger.startswith("path_contains:")

    cycles = pd.Series(
        {
            "field_path": "diagnoses[].treatments[].number_of_cycles",
            "coverage": 0.8,
            "unique_count": 5,
            "mode_share": 0.4,
        }
    )
    rule, _ = apply_rules(cycles)
    assert rule is None
    rule, _ = apply_rules(cycles, no_landmark=True)
    assert rule == "R0_label_leak"

    disease_response = pd.Series(
        {
            "field_path": "follow_ups[].disease_response",
            "coverage": 0.99,
            "unique_count": 2,
            "mode_share": 0.6,
        }
    )
    rule, _ = apply_rules(disease_response)
    assert rule == "R0_label_leak"

    figo = pd.Series(
        {
            "field_path": "diagnoses[].figo_staging_edition_year",
            "coverage": 0.8,
            "unique_count": 3,
            "mode_share": 0.4,
        }
    )
    rule, _ = apply_rules(figo)
    assert rule is None

    year_of_diagnosis = pd.Series(
        {
            "field_path": "diagnoses[].year_of_diagnosis",
            "coverage": 0.99,
            "unique_count": 10,
            "mode_share": 0.2,
        }
    )
    rule, _ = apply_rules(year_of_diagnosis)
    assert rule == "R0_label_leak"

    timepoint = pd.Series(
        {
            "field_path": "follow_ups[].other_clinical_attributes[].timepoint_category",
            "coverage": 0.99,
            "unique_count": 4,
            "mode_share": 0.5,
        }
    )
    rule, _ = apply_rules(timepoint)
    assert rule == "R0_label_leak"

    year_of_birth = pd.Series(
        {
            "field_path": "demographic.year_of_birth",
            "coverage": 0.9,
            "unique_count": 20,
            "mode_share": 0.1,
        }
    )
    rule, _ = apply_rules(year_of_birth)
    assert rule is None

    review = pd.Series(
        {
            "field_path": "diagnoses[].pathology_details[].consistent_pathology_review",
            "coverage": 0.9,
            "unique_count": 2,
            "mode_share": 0.5,
        }
    )
    rule, _ = apply_rules(review)
    assert rule is None
    rule, _ = apply_rules(review, no_landmark=True)
    assert rule == "R0_label_leak"

    index_date = pd.Series(
        {
            "field_path": "index_date",
            "coverage": 1.0,
            "unique_count": 1,
            "mode_share": 1.0,
        }
    )
    rule, _ = apply_rules(index_date)
    assert rule == "R1_admin"

    batch_id = pd.Series(
        {
            "field_path": "batch_id",
            "coverage": 1.0,
            "unique_count": 4,
            "mode_share": 0.4,
        }
    )
    rule, _ = apply_rules(batch_id)
    assert rule == "R1_admin"

    tumor_origin = pd.Series(
        {
            "field_path": "diagnoses[].tumor_of_origin",
            "coverage": 0.8,
            "unique_count": 10,
            "mode_share": 0.2,
        }
    )
    rule, _ = apply_rules(tumor_origin)
    assert rule is None
    rule, _ = apply_rules(tumor_origin, no_landmark=True)
    assert rule == "R0_label_leak"

    coverage_drop = pd.Series(
        {
            "field_path": "diagnoses[].ajcc_pathologic_t",
            "coverage": 0.4,
            "unique_count": 5,
            "mode_share": 0.4,
        }
    )
    rule, _ = apply_rules(coverage_drop, min_coverage=0.5)
    assert rule == "R3_coverage"

    unique_drop = pd.Series(
        {
            "field_path": "diagnoses[].ajcc_pathologic_t",
            "coverage": 0.9,
            "unique_count": 3,
            "mode_share": 0.4,
        }
    )
    rule, _ = apply_rules(unique_drop, min_unique=4)
    assert rule == "R4_degenerate"

    mode_drop = pd.Series(
        {
            "field_path": "diagnoses[].ajcc_pathologic_t",
            "coverage": 0.9,
            "unique_count": 3,
            "mode_share": 0.8,
        }
    )
    rule, _ = apply_rules(mode_drop, max_mode_share=0.7)
    assert rule == "R4_degenerate"


def test_field_bank_landmark_masks_post_last_time():
    from argparse import Namespace

    from discovery.field_bank import extract_field_bank_raw_values, extract_field_bank_value
    from discovery.landmark import parse_landmark_options, patient_landmark, timed_family_for_field

    case = {
        "submitter_id": "TCGA-AA-0001",
        "demographic": {"vital_status": "Alive", "race": "white"},
        "diagnoses": [
            {
                "days_to_diagnosis": 0,
                "days_to_last_follow_up": 100,
                "primary_diagnosis": "Adenocarcinoma",
                "updated_datetime": "2024-01-01T00:00:00+00:00",
                "treatments": [
                    {
                        "number_of_cycles": 4,
                        "days_to_treatment_start": 10,
                        "updated_datetime": "2024-01-11T00:00:00+00:00",
                    },
                    {
                        "number_of_cycles": 8,
                        "days_to_treatment_start": 150,
                        "updated_datetime": "2024-06-01T00:00:00+00:00",
                    },
                ],
            }
        ],
        "follow_ups": [
            {
                "ecog_performance_status": "0",
                "days_to_follow_up": 80,
                "updated_datetime": "2024-03-01T00:00:00+00:00",
            },
            {
                "ecog_performance_status": "3",
                "days_to_follow_up": 200,
                "updated_datetime": "2024-08-01T00:00:00+00:00",
            },
        ],
    }
    landmark = patient_landmark(case, landmark_time=100)
    assert landmark["last_time"] == 100
    assert timed_family_for_field("diagnoses[].treatments[].number_of_cycles")[0] == "diagnoses_treatments"
    assert extract_field_bank_raw_values(
        case, "diagnoses[].treatments[].number_of_cycles", landmark_time=100
    ) == [4]
    assert extract_field_bank_raw_values(
        case, "follow_ups[].ecog_performance_status", landmark_time=100
    ) == ["0"]
    assert extract_field_bank_raw_values(case, "demographic.race", landmark_time=100) == ["white"]
    value, valid = extract_field_bank_value(
        case, "follow_ups[].ecog_performance_status", landmark_time=100
    )
    assert valid is True
    assert value == "0"
    missing, missing_valid = extract_field_bank_value(
        {
            "submitter_id": "TCGA-AA-0002",
            "demographic": {"vital_status": "Alive"},
            "follow_ups": [
                {
                    "ecog_performance_status": "1",
                    "updated_datetime": "2024-02-01T00:00:00+00:00",
                }
            ],
        },
        "follow_ups[].ecog_performance_status",
        landmark_time=100,
    )
    assert missing_valid is False
    assert missing == "not reported"
    unmasked = extract_field_bank_raw_values(
        case, "follow_ups[].ecog_performance_status", landmark=False
    )
    assert unmasked == ["0", "3"]
    later = extract_field_bank_raw_values(
        case, "follow_ups[].ecog_performance_status", landmark_time=200
    )
    assert later == ["0", "3"]

    late_write = {
        "submitter_id": "TCGA-AA-0003",
        "demographic": {"vital_status": "Alive"},
        "diagnoses": [
            {
                "days_to_diagnosis": 0,
                "days_to_last_follow_up": 100,
                "updated_datetime": "2024-01-01T00:00:00+00:00",
                "treatments": [
                    {
                        "number_of_cycles": 6,
                        "days_to_treatment_start": 20,
                        "updated_datetime": "2024-12-01T00:00:00+00:00",
                    }
                ],
            }
        ],
    }
    assert extract_field_bank_raw_values(
        late_write, "diagnoses[].treatments[].number_of_cycles", landmark_time=100
    ) == [6]
    with pytest.raises(ValueError, match="landmark_time"):
        extract_field_bank_raw_values(case, "follow_ups[].ecog_performance_status")
    with pytest.raises(ValueError, match="landmark_time"):
        parse_landmark_options(Namespace(landmark_time=None))
    with pytest.raises(ValueError, match="landmark_time"):
        parse_landmark_options(Namespace(landmark_time="abc"))
    assert parse_landmark_options(Namespace(landmark_time="none")) == (False, None)
    assert parse_landmark_options(Namespace(landmark_time="365")) == (True, 365.0)
    assert parse_landmark_options(Namespace(landmark_time=365)) == (True, 365.0)

    n2_case = {
        "submitter_id": "TCGA-AA-0004",
        "demographic": {"vital_status": "Alive"},
        "diagnoses": [
            {
                "days_to_diagnosis": 0,
                "days_to_last_follow_up": 100,
                "treatments": [
                    {
                        "treatment_or_therapy": "no",
                        "treatment_type": "Pharmaceutical Therapy, NOS",
                    }
                ],
            }
        ],
    }
    assert extract_field_bank_raw_values(
        n2_case, "diagnoses[].treatments[].treatment_type", landmark_time=100
    ) == []


def test_filter_rules_r5_drop_keep():
    stage = pd.Series(
        {
            "field_path": "diagnoses[].ajcc_pathologic_stage",
            "coverage": 0.9,
            "unique_count": 5,
            "mode_share": 0.4,
        }
    )
    rule, trigger = apply_rules(stage)
    assert rule == "R5_derivable"
    assert "ajcc_pathologic_t" in trigger
    assert "ajcc_pathologic_n" in trigger
    assert "ajcc_pathologic_m" in trigger

    t_field = pd.Series(
        {
            "field_path": "diagnoses[].ajcc_pathologic_t",
            "coverage": 0.9,
            "unique_count": 5,
            "mode_share": 0.4,
        }
    )
    rule, _ = apply_rules(t_field)
    assert rule is None

    age_index = pd.Series(
        {
            "field_path": "demographic.age_at_index",
            "coverage": 0.9,
            "unique_count": 20,
            "mode_share": 0.1,
        }
    )
    rule, trigger = apply_rules(age_index)
    assert rule == "R5_derivable"
    assert "age_at_diagnosis" in trigger

    clinical_stage = pd.Series(
        {
            "field_path": "diagnoses[].ajcc_clinical_stage",
            "coverage": 0.8,
            "unique_count": 5,
            "mode_share": 0.3,
        }
    )
    rule, trigger = apply_rules(clinical_stage)
    assert rule == "R5_derivable"
    assert "ajcc_clinical_t" in trigger

    gender = pd.Series(
        {
            "field_path": "demographic.gender",
            "coverage": 0.9,
            "unique_count": 2,
            "mode_share": 0.6,
        }
    )
    rule, trigger = apply_rules(gender)
    assert rule == "R5_derivable"
    assert "sex_at_birth" in trigger

    year = pd.Series(
        {
            "field_path": "diagnoses[].year_of_diagnosis",
            "coverage": 0.9,
            "unique_count": 15,
            "mode_share": 0.2,
        }
    )
    rule, _ = apply_rules(year)
    assert rule == "R0_label_leak"

    edition = pd.Series(
        {
            "field_path": "diagnoses[].ajcc_staging_system_edition",
            "coverage": 0.9,
            "unique_count": 5,
            "mode_share": 0.4,
        }
    )
    rule, _ = apply_rules(edition)
    assert rule is None


def test_infer_type_stage_vs_class():
    assert infer_type("ajcc_pathologic_t", ["T1", "T2", "T3", "T4"], 4) == "ordinal_stage"
    assert infer_type("ajcc_clinical_stage", ["Stage I", "Stage II", "Stage IIIA"], 3) == "ordinal_stage"
    assert infer_type("race", ["white", "black", "asian"], 3) == "ordinal_class"
    assert infer_type("gender", ["male", "female"], 2) == "ordinal_class"
    assert infer_type("icd_10_code", ["C18.2", "C18.7", "C20"], 3) == "ordinal_class"
    assert infer_type("age_at_diagnosis", [61, 62, 70], 3) == "numeric"


def test_dataset_field_bank_dir_defaults_to_prompt():
    assert dataset_field_bank_dir("TCGA-BRCA", landmark_tag="landmark_365") == PROJECT_ROOT / "outputs" / "TCGA-BRCA" / "field_bank" / "prompt" / "landmark_365"


def test_dataset_field_bank_dir_onehot():
    assert dataset_field_bank_dir("TCGA-BRCA", "onehot", "landmark_none") == PROJECT_ROOT / "outputs" / "TCGA-BRCA" / "field_bank" / "onehot" / "landmark_none"


def test_dataset_greedy_dir_onehot():
    assert dataset_greedy_dir("TCGA-BRCA", "onehot", "landmark_0") == PROJECT_ROOT / "outputs" / "TCGA-BRCA" / "greedy" / "onehot" / "landmark_0"


def test_dataset_univariate_dir_prompt():
    assert dataset_univariate_dir("TCGA_LIHC", "prompt", "landmark_365") == PROJECT_ROOT / "outputs" / "TCGA_LIHC" / "univariate" / "prompt" / "landmark_365"


def test_dataset_linear_probe_dir_prompt():
    assert dataset_linear_probe_dir("TCGA_LIHC", "prompt", "landmark_none") == PROJECT_ROOT / "outputs" / "TCGA_LIHC" / "linear_probe" / "prompt" / "landmark_none"


def test_dataset_dirs_include_longitudinal_experiment():
    assert dataset_field_bank_dir(
        "TCGA-BRCA", "prompt", "landmark_365", experiment="longitudinal"
    ) == PROJECT_ROOT / "outputs" / "TCGA-BRCA" / "longitudinal" / "field_bank" / "prompt" / "landmark_365"
    assert dataset_greedy_dir(
        "TCGA-BRCA", "onehot", "landmark_none", experiment="longitudinal"
    ) == PROJECT_ROOT / "outputs" / "TCGA-BRCA" / "longitudinal" / "greedy" / "onehot" / "landmark_none"
    assert dataset_univariate_dir(
        "TCGA_LIHC", "prompt", "landmark_365", experiment="longitudinal"
    ) == PROJECT_ROOT / "outputs" / "TCGA_LIHC" / "longitudinal" / "univariate" / "prompt" / "landmark_365"
    assert dataset_linear_probe_dir(
        "TCGA_LIHC", "prompt", "landmark_none"
    ) == PROJECT_ROOT / "outputs" / "TCGA_LIHC" / "linear_probe" / "prompt" / "landmark_none"
    assert normalize_experiment("") == ""
    assert normalize_experiment("longitudinal") == "longitudinal"


def test_invalid_encoding_raises():
    with pytest.raises(ValueError, match="unsupported encoding"):
        validate_encoding("hash")
    with pytest.raises(ValueError, match="unsupported encoding"):
        dataset_field_bank_dir("TCGA-BRCA", "hash")
    with pytest.raises(ValueError, match="unsupported encoding"):
        dataset_greedy_dir("TCGA-BRCA", "hash")
    with pytest.raises(ValueError, match="unsupported encoding"):
        dataset_univariate_dir("TCGA-BRCA", "hash")
        dataset_linear_probe_dir("TCGA-BRCA", "hash")


def test_field_bank_main_rejects_unknown_encoding():
    parser = build_field_bank_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--dataset", "TCGA-BRCA", "--encoding", "hash", "--landmark_time", "none"])
    with pytest.raises(SystemExit):
        field_bank_main(["--dataset", "TCGA-BRCA", "--encoding", "hash", "--landmark_time", "none"])


def test_field_bank_parser_landmark_time():
    parser = build_field_bank_parser()
    args = parser.parse_args(["--dataset", "TCGA-BRCA", "--landmark_time", "365"])
    assert args.landmark_time == "365"
    args = parser.parse_args(["--dataset", "TCGA-BRCA", "--landmark_time", "none"])
    assert args.landmark_time == "none"
    args = parser.parse_args(["--dataset", "TCGA-BRCA", "--landmark_time", "none,365"])
    assert args.landmark_time == "none,365"
    args = parser.parse_args(["--dataset", "TCGA-BRCA", "--landmark_time", "all"])
    assert args.landmark_time == "all"
    with pytest.raises(SystemExit):
        parser.parse_args(["--dataset", "TCGA-BRCA"])
    with pytest.raises(SystemExit):
        field_bank_main(["--dataset", "TCGA-BRCA"])


def test_landmark_time_accepts_csv_and_all(tmp_path):
    from argparse import Namespace

    from common.paths import (
        canonical_landmark_spec,
        parse_landmark_time_list,
        resolve_landmark_time_tokens,
    )
    from discovery.landmark import iter_landmark_args

    assert parse_landmark_time_list("none,365,365") == ["none", "365"]
    assert parse_landmark_time_list("all") == ["all"]
    assert canonical_landmark_spec("365,none") == "365,none"
    with pytest.raises(ValueError, match="混用"):
        parse_landmark_time_list("all,365")

    (tmp_path / "landmark_0").mkdir()
    (tmp_path / "landmark_365").mkdir()
    (tmp_path / "landmark_none").mkdir()
    (tmp_path / "other").mkdir()
    assert resolve_landmark_time_tokens("all", scan_roots=tmp_path) == ["0", "365", "none"]

    args = Namespace(landmark_time="none,365")
    tokens = [item.landmark_time for item in iter_landmark_args(args)]
    tags = [item.landmark_tag for item in iter_landmark_args(args)]
    assert tokens == ["none", "365"]
    assert tags == ["landmark_none", "landmark_365"]


def test_scan_labels_prefer_gdc_dictionary():
    from discovery.scan import GENERIC_LABELS, build_json_field_dict

    cases = [
        {
            "index_date": "Diagnosis",
            "state": "released",
            "demographic": {"sex_at_birth": "female"},
            "diagnoses": [{"year_of_diagnosis": 2012}],
        }
    ]
    dict_data = build_json_field_dict(cases, dataset_name="toy")
    assert "reference or anchor date" in dict_data["顶层字段"]["index_date"]
    assert dict_data["顶层字段"]["state"] == GENERIC_LABELS["state"]
    assert "sex at birth" in dict_data["demographic对象"]["sex_at_birth"].lower()
    assert "year of" in dict_data["diagnoses数组_每个对象"]["year_of_diagnosis"].lower()
    assert "确诊年份" not in dict_data["diagnoses数组_每个对象"]["year_of_diagnosis"]


def test_resolve_json_field_dict_path_skips_gdc_csv():
    from discovery.scan import resolve_json_field_dict_path
    from common.paths import DEFAULT_GDC_CLINICAL_DICTIONARY, dataset_field_dict_path

    explicit = resolve_json_field_dict_path("TCGA-BRCA", explicit_path=DEFAULT_GDC_CLINICAL_DICTIONARY)
    dataset_path = dataset_field_dict_path("TCGA-BRCA")
    if dataset_path.exists():
        assert explicit == dataset_path
    else:
        assert explicit.suffix.lower() != ".csv"

    with tempfile.TemporaryDirectory() as tmp:
        custom = Path(tmp) / "custom_fields.json"
        custom.write_text("{}", encoding="utf-8")
        assert resolve_json_field_dict_path("TCGA-BRCA", explicit_path=custom) == custom



if __name__ == "__main__":
    test_extract_path_and_primary_diagnosis()
    test_missingness_three_state()
    test_filter_rules()
    test_filter_rules_new_r0_r1_and_thresholds()
    test_filter_rules_r5_drop_keep()
    test_field_bank_landmark_masks_post_last_time()
    test_infer_type_stage_vs_class()
    test_dataset_field_bank_dir_defaults_to_prompt()
    test_dataset_field_bank_dir_onehot()
    test_dataset_greedy_dir_onehot()
    test_dataset_univariate_dir_prompt()
    test_dataset_linear_probe_dir_prompt()
    test_dataset_dirs_include_longitudinal_experiment()
    test_invalid_encoding_raises()
    test_field_bank_main_rejects_unknown_encoding()
    test_field_bank_parser_landmark_time()
    test_landmark_time_accepts_csv_and_all(Path(tempfile.mkdtemp()))
    test_scan_labels_prefer_gdc_dictionary()
    test_resolve_json_field_dict_path_skips_gdc_csv()
    print("ok")
