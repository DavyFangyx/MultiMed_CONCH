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
from common.paths import (
    PROJECT_ROOT,
    dataset_field_bank_dir,
    dataset_greedy_dir,
    dataset_greedy_results_dir,
    dataset_greedy_run_dir,
    dataset_linear_probe_dir,
    dataset_linear_probe_results_dir,
    dataset_univariate_dir,
    dataset_univariate_results_dir,
    dataset_univariate_run_dir,
    display_results_dir,
    normalize_experiment,
    result_experiment_name,
    validate_encoding,
)
from common.types import infer_type
from discovery.cli import build_field_bank_parser, field_bank_main
from discovery.filter import apply_rules


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


def test_primary_diagnosis_anchors_on_days_not_flag():
    """主诊断 = days 最小记录;GDC 的 primary-disease 标记不是时间锚点(SKCM 型错位)。"""
    diags = [
        {"diagnosis_is_primary_disease": "true", "days_to_diagnosis": 426, "ajcc_pathologic_t": None},
        {"diagnosis_is_primary_disease": "false", "days_to_diagnosis": 0, "ajcc_pathologic_t": "T1a"},
        {"diagnosis_is_primary_disease": "false", "days_to_diagnosis": 457},
    ]
    picked = get_primary_diagnosis(diags)
    assert picked["days_to_diagnosis"] == 0
    assert picked["ajcc_pathologic_t"] == "T1a"


def test_primary_diagnosis_negative_days_preferred():
    """轴上更早(负 days)的记录优先;天数缺失排最后。"""
    diags = [
        {"diagnosis_is_primary_disease": "false", "days_to_diagnosis": None},
        {"diagnosis_is_primary_disease": "true", "days_to_diagnosis": 0},
        {"diagnosis_is_primary_disease": "false", "days_to_diagnosis": -64, "ajcc_pathologic_t": "T2b"},
    ]
    assert get_primary_diagnosis(diags)["ajcc_pathologic_t"] == "T2b"


def test_primary_diagnosis_flag_tiebreak_and_fallback():
    # 同 days 时 flag=True 优先
    diags = [
        {"diagnosis_is_primary_disease": "false", "days_to_diagnosis": 0, "ajcc_pathologic_t": "T2"},
        {"diagnosis_is_primary_disease": "true", "days_to_diagnosis": 0, "ajcc_pathologic_t": "T1a"},
    ]
    assert get_primary_diagnosis(diags)["ajcc_pathologic_t"] == "T1a"
    # 全部无 days 时退回 flag 优先(与原行为一致)
    assert get_primary_diagnosis(
        [{"diagnosis_is_primary_disease": "false"}, {"diagnosis_is_primary_disease": "true"}]
    )["diagnosis_is_primary_disease"] == "true"
    # 空列表
    assert get_primary_diagnosis([]) == {}


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
    # 2026-10-08 口径对齐:no_mask(landmark off)不再整层删除 timed 层
    # (diagnoses[] / follow_ups[]),R0 只删结局字段本身——本字段两种口径下都保留。
    rule, _ = apply_rules(follow_up)
    assert rule is None

    cycles = pd.Series(
        {
            "field_path": "diagnoses[].treatments[].number_of_cycles",
            "coverage": 0.8,
            "unique_count": 5,
            "mode_share": 0.4,
        }
    )
    # no_mask 口径下同样保留(见上:不再按 landmark 开关整层删 timed 层)。
    rule, _ = apply_rules(cycles)
    assert rule is None

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


def test_filter_rules_r5_alias_and_r4_exempt():
    # R5_alias(2026-10-08 修订):同语义保留 canonical,别名剔除并记录 alias_of。
    stage = pd.Series(
        {
            "field_path": "diagnoses[].ajcc_pathologic_stage",
            "coverage": 0.9,
            "unique_count": 5,
            "mode_share": 0.4,
        }
    )
    rule, _ = apply_rules(stage)
    assert rule is None  # 复合分期不再与 T/N/M 互斥,独立保留

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
    rule, _ = apply_rules(age_index)
    assert rule is None  # canonical 保留

    age_diag = pd.Series(
        {
            "field_path": "diagnoses[].age_at_diagnosis",
            "coverage": 0.9,
            "unique_count": 20,
            "mode_share": 0.1,
        }
    )
    rule, trigger = apply_rules(age_diag)
    assert rule == "R5_alias"
    assert "demographic.age_at_index" in trigger

    relationship_age = pd.Series(
        {
            "field_path": "family_histories[].relationship_age_at_diagnosis",
            "coverage": 0.9,
            "unique_count": 20,
            "mode_share": 0.1,
        }
    )
    rule, _ = apply_rules(relationship_age)
    assert rule is None  # 叶子撞名不误伤:别名按完整路径匹配

    days_to_birth = pd.Series(
        {
            "field_path": "demographic.days_to_birth",
            "coverage": 0.9,
            "unique_count": 20,
            "mode_share": 0.1,
        }
    )
    rule, _ = apply_rules(days_to_birth)
    assert rule is None  # 单独保留为自有字段(2026-10-08)

    clinical_stage = pd.Series(
        {
            "field_path": "diagnoses[].ajcc_clinical_stage",
            "coverage": 0.8,
            "unique_count": 5,
            "mode_share": 0.3,
        }
    )
    rule, _ = apply_rules(clinical_stage)
    assert rule is None  # 复合临床分期独立保留

    gender = pd.Series(
        {
            "field_path": "demographic.gender",
            "coverage": 0.9,
            "unique_count": 2,
            "mode_share": 0.6,
        }
    )
    rule, trigger = apply_rules(gender)
    assert rule == "R5_alias"
    assert "sex_at_birth" in trigger

    # R4_exempt(2026-10-08):论文方案字段豁免 n_unique 与 mode_share 两个触发。
    sex_near_constant = pd.Series(
        {
            "field_path": "demographic.sex_at_birth",
            "coverage": 0.99,
            "unique_count": 2,
            "mode_share": 0.989,
        }
    )
    rule, _ = apply_rules(sex_near_constant, max_mode_share=0.95)
    assert rule is None

    sex_single_value = pd.Series(
        {
            "field_path": "demographic.sex_at_birth",
            "coverage": 0.97,
            "unique_count": 1,
            "mode_share": 1.0,
        }
    )
    rule, _ = apply_rules(sex_single_value, min_unique=2, max_mode_share=0.95)
    assert rule is None  # 真常数也豁免

    nonexempt_near_constant = pd.Series(
        {
            "field_path": "diagnoses[].laterality",
            "coverage": 0.9,
            "unique_count": 2,
            "mode_share": 0.98,
        }
    )
    rule, _ = apply_rules(nonexempt_near_constant, max_mode_share=0.95)
    assert rule == "R4_degenerate"  # 非清单字段 R4 原样生效

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
    assert dataset_field_bank_dir("TCGA-BRCA", "onehot", "no_mask") == PROJECT_ROOT / "outputs" / "TCGA-BRCA" / "field_bank" / "onehot" / "no_mask"


def test_dataset_greedy_dir_onehot():
    assert dataset_greedy_dir("TCGA-BRCA", "onehot", "landmark_0") == PROJECT_ROOT / "outputs" / "TCGA-BRCA" / "greedy" / "onehot" / "landmark_0"


def test_dataset_univariate_dir_prompt():
    assert dataset_univariate_dir("TCGA_LIHC", "prompt", "landmark_365") == PROJECT_ROOT / "outputs" / "TCGA_LIHC" / "univariate" / "prompt" / "landmark_365"


def test_dataset_linear_probe_dir_prompt():
    assert dataset_linear_probe_dir("TCGA_LIHC", "prompt", "no_mask") == PROJECT_ROOT / "outputs" / "TCGA_LIHC" / "linear_probe" / "prompt" / "no_mask"


def test_dataset_results_dirs():
    assert dataset_greedy_results_dir("TCGA-BRCA", "onehot", "landmark_0") == PROJECT_ROOT / "results" / "greedy" / "onehot" / "landmark_0" / "TCGA-BRCA"
    assert dataset_univariate_results_dir("TCGA_LIHC", "prompt", "landmark_365") == PROJECT_ROOT / "results" / "univariate" / "prompt" / "landmark_365" / "TCGA_LIHC"
    assert dataset_linear_probe_results_dir("TCGA_LIHC", "prompt", "no_mask") == PROJECT_ROOT / "results" / "linear_probe" / "prompt" / "no_mask" / "TCGA_LIHC"
    assert dataset_greedy_results_dir(
        "TCGA-BRCA", "onehot", "no_mask", experiment="longitudinal"
    ) == PROJECT_ROOT / "results" / "longitudinal_greedy" / "onehot" / "no_mask" / "TCGA-BRCA"
    assert dataset_greedy_run_dir(
        "CPTAC", "prompt", "landmark_730", "G4_37770ad1bc", "mlp_clinic_flatten"
    ) == PROJECT_ROOT / "results" / "greedy" / "prompt" / "landmark_730" / "CPTAC" / "runs" / "G4_37770ad1bc" / "mlp_clinic_flatten"
    assert dataset_univariate_run_dir(
        "TCGA_LIHC", "prompt", "landmark_365", "G1_deadbeef12", "mlp_clinic_flatten"
    ) == PROJECT_ROOT / "results" / "univariate" / "prompt" / "landmark_365" / "TCGA_LIHC" / "runs" / "G1_deadbeef12" / "mlp_clinic_flatten"
    assert dataset_greedy_run_dir(
        "TCGA-BRCA", "onehot", "no_mask", "G2_abc", "mlp_clinic_flatten", experiment="longitudinal"
    ) == PROJECT_ROOT / "results" / "longitudinal_greedy" / "onehot" / "no_mask" / "TCGA-BRCA" / "runs" / "G2_abc" / "mlp_clinic_flatten"
    assert dataset_univariate_results_dir(
        "TCGA_LIHC", "prompt", "landmark_365", experiment="longitudinal"
    ) == PROJECT_ROOT / "results" / "longitudinal_univariate" / "prompt" / "landmark_365" / "TCGA_LIHC"
    assert display_results_dir("greedy", "prompt", "landmark_0") == PROJECT_ROOT / "results_display" / "greedy" / "prompt" / "landmark_0"
    assert result_experiment_name("greedy", "") == "greedy"
    assert result_experiment_name("univariate", "longitudinal") == "longitudinal_univariate"


def test_dataset_dirs_include_longitudinal_experiment():
    assert dataset_field_bank_dir(
        "TCGA-BRCA", "prompt", "landmark_365", experiment="longitudinal"
    ) == PROJECT_ROOT / "outputs" / "TCGA-BRCA" / "longitudinal" / "field_bank" / "prompt" / "landmark_365"
    assert dataset_greedy_dir(
        "TCGA-BRCA", "onehot", "no_mask", experiment="longitudinal"
    ) == PROJECT_ROOT / "outputs" / "TCGA-BRCA" / "longitudinal" / "greedy" / "onehot" / "no_mask"
    assert dataset_univariate_dir(
        "TCGA_LIHC", "prompt", "landmark_365", experiment="longitudinal"
    ) == PROJECT_ROOT / "outputs" / "TCGA_LIHC" / "longitudinal" / "univariate" / "prompt" / "landmark_365"
    assert dataset_linear_probe_dir(
        "TCGA_LIHC", "prompt", "no_mask"
    ) == PROJECT_ROOT / "outputs" / "TCGA_LIHC" / "linear_probe" / "prompt" / "no_mask"
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
    with pytest.raises(ValueError, match="unsupported encoding"):
        dataset_linear_probe_dir("TCGA-BRCA", "hash")
    with pytest.raises(ValueError, match="unsupported encoding"):
        dataset_greedy_results_dir("TCGA-BRCA", "hash", "no_mask")
    with pytest.raises(ValueError, match="unsupported encoding"):
        dataset_linear_probe_results_dir("TCGA-BRCA", "hash", "no_mask")
    with pytest.raises(ValueError, match="no longitudinal results tree"):
        dataset_linear_probe_results_dir("TCGA_LIHC", "prompt", "no_mask", experiment="longitudinal")


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
    (tmp_path / "no_mask").mkdir()
    (tmp_path / "other").mkdir()
    assert resolve_landmark_time_tokens("all", scan_roots=tmp_path) == ["0", "365", "none"]

    args = Namespace(landmark_time="none,365")
    tokens = [item.landmark_time for item in iter_landmark_args(args)]
    tags = [item.landmark_tag for item in iter_landmark_args(args)]
    assert tokens == ["none", "365"]
    assert tags == ["no_mask", "landmark_365"]


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


def test_field_stats_case_values_landmark_matches_field_bank():
    from discovery.field_bank import extract_field_bank_raw_values
    from discovery.landmark import patient_landmark, resolve_landmark
    from discovery.stats import _case_field_values

    case = {
        "submitter_id": "TCGA-AA-0001",
        "demographic": {"vital_status": "Alive", "race": "white"},
        "diagnoses": [
            {
                "days_to_diagnosis": 0,
                "days_to_last_follow_up": 100,
                "primary_diagnosis": "Adenocarcinoma",
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
    state = resolve_landmark(case, landmark=True, landmark_time=100)
    assert state == patient_landmark(case, landmark_time=100)

    # landmark 路径与 field bank 提取逐位一致(states 为 None)
    for field in (
        "diagnoses[].treatments[].number_of_cycles",
        "follow_ups[].ecog_performance_status",
        "demographic.race",
    ):
        valid_vals, states, raw_vals = _case_field_values(
            case, field, landmark_state=state, landmark_time=100
        )
        assert states is None
        assert valid_vals == extract_field_bank_raw_values(
            case, field, landmark=state, landmark_time=100
        )
        assert raw_vals  # raw 提取始终存在(masked_count 审计用)

    # 官方路径(landmark_state=None)行为不变
    valid_vals, states, raw_vals = _case_field_values(
        case, "follow_ups[].ecog_performance_status", landmark_state=None
    )
    assert valid_vals == ["0", "3"]
    assert states == ["valid", "valid"]


def test_stats_parser_landmark_time_default_none():
    from discovery.cli import build_stats_parser

    assert build_stats_parser().parse_args([]).landmark_time == "none"
    assert build_stats_parser().parse_args(["--landmark_time", "0"]).landmark_time == "0"


def test_filter_parser_out_suffix_and_r3_default():
    from discovery.cli import build_filter_parser

    args = build_filter_parser().parse_args(["--landmark_time", "0", "--out_suffix", "t0stats"])
    assert args.out_suffix == "t0stats"
    assert args.stats_csv is None  # 扶正后默认 None,由 run_field_filter 按 landmark-first 解析
    assert args.R3_coverage == 0.30
    assert args.R4_n_unique == 2
    assert args.R4_mode_share == 0.95


def test_resolve_filter_stats_path_landmark_first(tmp_path, monkeypatch):
    import discovery.filter as filter_mod

    shared_raw = tmp_path / "field_stats.csv"
    tagged = tmp_path / "landmark_0" / "field_stats.csv"
    tagged.parent.mkdir(parents=True)
    shared_raw.write_text("x", encoding="utf-8")
    monkeypatch.setattr(filter_mod, "shared_field_stats_path", lambda tag=None: (tagged if tag else shared_raw))

    # 显式 --stats_csv 始终覆盖
    explicit = tmp_path / "explicit.csv"
    assert filter_mod.resolve_filter_stats_path(str(explicit), "landmark_0") == explicit
    # landmark 开启且 tag 统计存在 → landmark-first
    tagged.write_text("x", encoding="utf-8")
    assert filter_mod.resolve_filter_stats_path(None, "landmark_0") == tagged
    # tag 统计不存在 → 回退 raw
    tagged.unlink()
    assert filter_mod.resolve_filter_stats_path(None, "landmark_0") == shared_raw
    # 无 landmark → raw
    assert filter_mod.resolve_filter_stats_path(None, None) == shared_raw


def test_paths_landmark_stats_and_out_suffix():
    from common.paths import (
        dataset_exclusion_log_path,
        dataset_field_registry_path,
        dataset_field_stats_path,
        dataset_filter_log_dir,
        dataset_kept_fields_path,
        shared_field_stats_path,
        shared_kept_fields_path,
    )

    assert dataset_field_stats_path("TCGA-BRCA") == PROJECT_ROOT / "rawdata_stats" / "TCGA-BRCA" / "field_stats.csv"
    assert (
        dataset_field_stats_path("TCGA-BRCA", "landmark_0")
        == PROJECT_ROOT / "rawdata_stats" / "TCGA-BRCA" / "landmark_0" / "field_stats.csv"
    )
    assert shared_field_stats_path() == PROJECT_ROOT / "rawdata_stats" / "_shared" / "field_stats.csv"
    assert (
        shared_field_stats_path("landmark_0")
        == PROJECT_ROOT / "rawdata_stats" / "_shared" / "landmark_0" / "field_stats.csv"
    )
    assert (
        dataset_kept_fields_path("TCGA-BRCA", "landmark_0", out_suffix="t0stats")
        == PROJECT_ROOT / "rawdata_stats" / "TCGA-BRCA" / "landmark_0_t0stats" / "kept_fields.json"
    )
    assert (
        shared_kept_fields_path("landmark_0", out_suffix="t0stats")
        == PROJECT_ROOT / "rawdata_stats" / "_shared" / "landmark_0_t0stats" / "kept_fields.json"
    )
    assert (
        dataset_filter_log_dir("TCGA-BRCA", "landmark_0", out_suffix="t0stats")
        == PROJECT_ROOT / "rawdata_stats" / "TCGA-BRCA" / "landmark_0_t0stats" / "fliter_log"
    )
    assert (
        dataset_exclusion_log_path("TCGA-BRCA", "landmark_0", out_suffix="t0stats")
        == PROJECT_ROOT / "rawdata_stats" / "TCGA-BRCA" / "landmark_0_t0stats" / "fliter_log" / "exclusion_log.csv"
    )
    assert (
        dataset_field_registry_path("TCGA-BRCA", "landmark_0", out_suffix="t0stats")
        == PROJECT_ROOT / "rawdata_stats" / "TCGA-BRCA" / "landmark_0_t0stats" / "fliter_log" / "field_registry.csv"
    )
    with pytest.raises(ValueError):
        dataset_kept_fields_path("TCGA-BRCA", "landmark_0", out_suffix="bad-suffix")
    with pytest.raises(ValueError):
        dataset_field_stats_path("TCGA-BRCA", "landmark_0_t0stats")



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
