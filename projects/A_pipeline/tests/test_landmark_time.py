"""Tests for the Test_1b landmark extension (`--landmark_time` / `--landmark_shift`).

Covers the three classical landmark requirements of z_notes/Test_series_spec.md
§2.5 on the A_pipeline side:

1. covariate mask  - `src.landmark.mask_case`: only timed slots with
   t_hi <= T survive, untimed families and slot-less records stay untouched,
   `landmark_time=None` is bit-for-bit the legacy behaviour;
2. risk set        - `src.landmark_labels.build_landmark_label_file`: patients
   with ground_truth_time <= T leave the label file (i.e. every fold);
3. time shift      - the same label file shifts the endpoint time by -T, with
   `--landmark_shift off` keeping the un-shifted variant for the invariance
   self-check.

Plus the routing: landmark arms write to their own output / results / queue /
conf paths and never touch the legacy `A_manual` ones.

No real CONCH encoding and no real Clinic_Analyzer run happen here.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT / "src"))
from common.paths import RESULTS_ROOT, test_results_dir as _resolve_results_dir  # noqa: E402

# Test 系列命名公约: 结果臂目录(迁移前 = A_manual/A_manual_landmark,
# 迁移后 = Test_2b/arm_A/arm_B;断言随解析,两种状态都成立)
ARM_A = _resolve_results_dir("Test_2b/arm_A").relative_to(RESULTS_ROOT)
ARM_B = _resolve_results_dir("Test_2b/arm_B").relative_to(RESULTS_ROOT)


A_PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(A_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(A_PIPELINE_ROOT))

from src.baseline import baseline_scheme_output_dir, load_baseline_scheme_fields  # noqa: E402
from src.cindex import (  # noqa: E402
    analyzer_exp_group,
    conf_filename,
    conf_text,
    iter_cindex_jobs,
    landmark_scheme_name,
    result_table_dir,
    scheme_output_dir,
    summarize_dataset,
)
from src.cli import main as a_pipeline_main  # noqa: E402
from src.config import SCHEME_FIELDS, load_custom_schemes, reset_scheme_registry  # noqa: E402
from src.extract import extract_values  # noqa: E402
from src.hgcn_clinic import load_hgcn_scheme_fields  # noqa: E402
from src.json2prompt import run_json2prompt, generate_prompt_row  # noqa: E402
from src.landmark import (  # noqa: E402
    LANDMARK_NONE_TAG,
    LandmarkSetting,
    landmark_dir,
    mask_case,
    parse_landmark_setting,
)
from src.landmark_labels import build_landmark_label_file  # noqa: E402
from src.paths import DEFAULT_TEMPLATE_DIR  # noqa: E402


def _load_scheme_fields():
    reset_scheme_registry()
    load_custom_schemes(DEFAULT_TEMPLATE_DIR)
    load_baseline_scheme_fields(SCHEME_FIELDS)
    load_hgcn_scheme_fields(SCHEME_FIELDS)


# --------------------------------------------------------------------------
# 1. `--landmark_time` parsing
# --------------------------------------------------------------------------


def test_parse_landmark_setting_modes():
    absent = parse_landmark_setting(None)
    assert (absent.provided, absent.use_landmark, absent.landmark_time) == (False, False, None)
    assert absent.encode_subdir == "" and absent.arm_tag == ""
    assert parse_landmark_setting("").provided is False

    none_arm = parse_landmark_setting("none")
    assert (none_arm.provided, none_arm.use_landmark, none_arm.landmark_time) == (True, False, None)
    # landmark_none keeps the existing output dirs (only the cindex table moves).
    assert none_arm.encode_subdir == ""
    assert none_arm.arm_tag == LANDMARK_NONE_TAG == "landmark_none"

    for token, days in (("0", 0), ("365", 365), ("730", 730)):
        setting = parse_landmark_setting(token)
        assert (setting.provided, setting.use_landmark, setting.landmark_time) == (True, True, days)
        assert setting.encode_subdir == f"landmark_{days}"
        assert setting.arm_tag == f"landmark_{days}"


def test_parse_landmark_setting_rejects_bad_tokens():
    for bad in ("-1", "1.5", "yes", True):
        with pytest.raises(ValueError):
            parse_landmark_setting(bad)


def test_landmark_dir_keeps_legacy_path_when_off(tmp_path):
    base = tmp_path / "MULTISURV"
    assert landmark_dir(base, "") == base
    assert landmark_dir(base, "landmark_0") == base / "landmark_0"


# --------------------------------------------------------------------------
# 2. covariate mask (only timed slots)
# --------------------------------------------------------------------------


def _timed_case():
    """One primary diagnosis at day 400, bounded by a follow-up at day 700.

    The treatment/OCA slots inherit the same upper bound, so T=730 lets the
    whole timed universe through while T=365 masks all of it.
    """
    return {
        "submitter_id": "TCGA-XX-0001",
        "demographic": {
            "age_at_index": 60,
            "sex_at_birth": "male",
            "race": "white",
            "vital_status": "Alive",
            "days_to_last_follow_up": 700,
        },
        "project": {"project_id": "TCGA-KIRC"},
        "diagnoses": [
            {
                "diagnosis_is_primary_disease": "true",
                "primary_diagnosis": "Adenocarcinoma",
                "ajcc_pathologic_stage": "Stage IV",
                "prior_malignancy": "no",
                "days_to_diagnosis": 400,
                "treatments": [
                    {
                        "treatment_type": "Pharmaceutical Therapy, NOS",
                        "treatment_or_therapy": "yes",
                        "days_to_treatment_start": 420,
                    }
                ],
            }
        ],
        "follow_ups": [
            {
                "days_to_follow_up": 700,
                "ecog_performance_status": "1",
                "other_clinical_attributes": [{"bmi": 24.5, "days_to_comorbidity": 690}],
            }
        ],
    }


TIMED_FIELDS = [
    "diagnoses[].ajcc_pathologic_stage",
    "diagnoses[].prior_malignancy",
    "derived.pharmaceutical_therapy",
    "follow_ups[].ecog_performance_status",
    "follow_ups[].other_clinical_attributes[].bmi",
]
UNTIMED_FIELDS = ["demographic.age_at_index", "demographic.sex_at_birth", "project.project_id"]


def test_extract_values_without_landmark_is_legacy():
    case = _timed_case()
    legacy = extract_values(case)
    assert extract_values(case, landmark_time=None) == legacy
    # `mask_case` must not copy the case when the landmark is off.
    assert mask_case(case, None) is case
    assert legacy["diagnoses[].ajcc_pathologic_stage"] == "Stage IV"


def test_mask_only_drops_timed_slots():
    legacy = extract_values(_timed_case())

    at_365 = extract_values(_timed_case(), landmark_time=365)
    for field in TIMED_FIELDS:
        assert at_365[field] != legacy[field], field
    for field in UNTIMED_FIELDS:
        assert at_365[field] == legacy[field], field

    at_730 = extract_values(_timed_case(), landmark_time=730)
    for field in TIMED_FIELDS + UNTIMED_FIELDS:
        assert at_730[field] == legacy[field], field

    assert set(at_365) == set(legacy)


def test_mask_keeps_records_the_time_model_never_times():
    """A negative-therapy record has no slot -> the mask must not remove it."""
    case = {
        "submitter_id": "TCGA-XX-0002",
        "demographic": {"vital_status": "Alive", "days_to_last_follow_up": 700},
        "diagnoses": [
            {
                "diagnosis_is_primary_disease": "true",
                "primary_diagnosis": "Adenocarcinoma",
                "days_to_diagnosis": 0,
                "treatments": [
                    {
                        "treatment_type": "Radiation Therapy, NOS",
                        "treatment_or_therapy": "no",
                        "days_to_treatment_start": 420,
                    }
                ],
            }
        ],
    }
    legacy = extract_values(case)
    masked = extract_values(case, landmark_time=0)
    assert legacy["derived.radiation_therapy"] == "no"
    assert masked["derived.radiation_therapy"] == legacy["derived.radiation_therapy"]


def test_mask_drops_unlocated_diagnosis():
    case = {
        "submitter_id": "TCGA-XX-0003",
        "demographic": {"vital_status": "Alive", "days_to_last_follow_up": 700},
        "diagnoses": [
            {
                "diagnosis_is_primary_disease": "true",
                "primary_diagnosis": "Adenocarcinoma",
                "ajcc_pathologic_stage": "Stage II",
            }
        ],
    }
    assert extract_values(case)["diagnoses[].ajcc_pathologic_stage"] == "Stage II"
    masked = extract_values(case, landmark_time=0)
    assert masked["diagnoses[].ajcc_pathologic_stage"] == "Stage X"


def test_mask_case_copies_only_touched_levels():
    case = _timed_case()
    masked = mask_case(case, 0)
    assert masked is not case
    assert masked["demographic"] is case["demographic"]  # untimed level untouched
    assert masked["diagnoses"] == []  # the only diagnosis failed the mask
    assert len(case["diagnoses"]) == 1  # source case not mutated


# --------------------------------------------------------------------------
# 3. json2prompt / encode / baseline output layout
# --------------------------------------------------------------------------


def _write_json_dir(tmp_path: Path) -> Path:
    import json

    json_path = tmp_path / "cases.json"
    json_path.write_text(json.dumps([_timed_case()]), encoding="utf-8")
    return json_path


def test_json2prompt_landmark_layout_and_values(tmp_path):
    _load_scheme_fields()
    json_path = _write_json_dir(tmp_path)
    prompt_root = tmp_path / "outputs" / "TCGA-KIRC" / "A_manual"

    legacy_out = Path(
        run_json2prompt(
            json_path=str(json_path),
            scheme="L5",
            template_dir=DEFAULT_TEMPLATE_DIR,
            prompt_dir=str(prompt_root),
            dataset_name="TCGA-KIRC",
        )
    )
    assert legacy_out == prompt_root / "L5" / "prompts.csv"

    masked_out = Path(
        run_json2prompt(
            json_path=str(json_path),
            scheme="L5",
            template_dir=DEFAULT_TEMPLATE_DIR,
            prompt_dir=str(prompt_root),
            dataset_name="TCGA-KIRC",
            landmark_time=0,
            landmark_subdir="landmark_0",
        )
    )
    assert masked_out == prompt_root / "L5" / "landmark_0" / "prompts.csv"

    legacy_df = pd.read_csv(legacy_out)
    masked_df = pd.read_csv(masked_out)
    # Same field set: the two arms may only differ by the mask.
    assert list(legacy_df.columns) == list(masked_df.columns)
    assert len(legacy_df) == len(masked_df) == 1
    assert legacy_df["patient_id"].tolist() == masked_df["patient_id"].tolist()

    changed = [col for col in legacy_df.columns if legacy_df[col][0] != masked_df[col][0]]
    assert changed == [
        # diagnoses[] and follow_ups[] are timed families -> masked at t0
        "diagnoses_primary_diagnosis_template",
        "diagnoses_prior_malignancy_template",
        "diagnoses_ajcc_pathologic_stage_template",
        "follow_ups_ecog_performance_status_template",
        "follow_ups_other_clinical_attributes_bmi_template",
    ]
    # demographic.* is untimed: byte-identical across the arms
    assert masked_df["demographic_age_at_index_template"][0] == legacy_df["demographic_age_at_index_template"][0]
    assert masked_df["demographic_age_at_index_template"][0] == "The patient is 60 years old at index."


def test_generate_prompt_row_passes_landmark_through():
    _load_scheme_fields()
    templates = {
        "demographic.age_at_index": "Age {}.",
        "demographic.sex_at_birth": "Sex {}.",
        "demographic.race": "Race {}.",
        "exposures[].alcohol_history": "Alcohol {}.",
        "diagnoses[].primary_diagnosis": "Primary {}.",
        "diagnoses[].site_of_resection_or_biopsy": "Site {}.",
        "diagnoses[].morphology": "Morphology {}.",
        "follow_ups[].other_clinical_attributes[].bmi": "BMI {}.",
        "exposures[].cigarettes_per_day": "Cigarettes {}.",
        "derived.radiation_therapy": "Radiation {}.",
        "derived.pharmaceutical_therapy": "Pharma {}.",
    }
    legacy = generate_prompt_row(_timed_case(), templates, "HGCN_ESCA", dataset_name="TCGA-KIRC")
    masked = generate_prompt_row(
        _timed_case(), templates, "HGCN_ESCA", landmark_time=0, dataset_name="TCGA-KIRC"
    )
    assert legacy["demographic_age_at_index_template"] == "Age 60."
    assert masked["demographic_age_at_index_template"] == "Age 60."
    assert legacy["follow_ups_other_clinical_attributes_bmi_template"] == "BMI 24.5."
    assert masked["follow_ups_other_clinical_attributes_bmi_template"] == "BMI not reported."
    assert legacy["derived_pharmaceutical_therapy_template"] == "Pharma yes."
    assert masked["derived_pharmaceutical_therapy_template"] == "Pharma unknown."


def test_baseline_scheme_output_dir_landmark_subdir(tmp_path):
    root = tmp_path / "outputs"
    assert baseline_scheme_output_dir(root, "D0") == root / "D0"
    assert baseline_scheme_output_dir(root, "HGCN_UCEC") == root / "baseline" / "HGCN_UCEC"
    assert baseline_scheme_output_dir(root, "D0", "landmark_0") == root / "D0" / "landmark_0"
    assert (
        baseline_scheme_output_dir(root, "HGCN_UCEC", "landmark_365")
        == root / "baseline" / "HGCN_UCEC" / "landmark_365"
    )


# --------------------------------------------------------------------------
# 4. cindex routing: own subtree, own queue names, legacy untouched
# --------------------------------------------------------------------------


def test_landmark_paths_never_touch_legacy_a_manual(tmp_path):
    results_root = tmp_path / "results"
    assert result_table_dir("TCGA-READ", results_root) == results_root / ARM_A / "TCGA-READ"
    assert (
        result_table_dir("TCGA-READ", results_root, landmark_tag="landmark_0")
        == results_root / ARM_B / "TCGA-READ"
    )
    assert (
        result_table_dir("TCGA-READ", results_root, landmark_tag=LANDMARK_NONE_TAG)
        == results_root / ARM_B / "TCGA-READ"
    )
    assert analyzer_exp_group() == f"{ARM_A}/runs"
    assert analyzer_exp_group("landmark_0") == f"{ARM_B}/runs"

    # landmark_none = the reported-value arm: same embedding dir as today.
    assert str(scheme_output_dir("TCGA-READ", "L0", str(tmp_path), landmark_subdir="")).endswith(
        "/outputs/TCGA-READ/A_manual/L0/embeddings/pt"
    )
    assert str(
        scheme_output_dir("TCGA-READ", "L0", str(tmp_path), landmark_subdir="landmark_0")
    ).endswith("/outputs/TCGA-READ/A_manual/L0/landmark_0/embeddings/pt")
    assert scheme_output_dir("TCGA-READ", "D0", str(tmp_path), landmark_subdir="") == Path(
        str(tmp_path)
    ) / "TCGA-READ" / "A_manual" / "D0" / "embeddings" / "pt"
    assert scheme_output_dir("TCGA-READ", "D0", str(tmp_path), landmark_subdir="landmark_0") == Path(
        str(tmp_path)
    ) / "TCGA-READ" / "A_manual" / "D0" / "landmark_0" / "embeddings" / "pt"


def test_landmark_scheme_and_conf_names():
    assert landmark_scheme_name("MULTISURV") == "MULTISURV"
    assert landmark_scheme_name("MULTISURV", "landmark_0") == "MULTISURV__landmark_0"
    assert conf_filename("tcga_brca", "MULTISURV", "clinic_cox") == "tcga_brca__MULTISURV__clinic_cox.conf"
    assert (
        conf_filename("tcga_brca", "MULTISURV", "clinic_cox", "landmark_0")
        == "tcga_brca__MULTISURV__landmark_0__clinic_cox.conf"
    )


def test_conf_text_landmark_routing(tmp_path):
    legacy = conf_text(
        study="tcga_brca",
        scheme="MULTISURV",
        modality="clinic_cox",
        clinic_dir=tmp_path / "clinic",
        split_dir=tmp_path / "splits",
        results_base=tmp_path / "results",
    )
    assert "EXP_GROUP='A_manual/runs'" in legacy
    assert "RUN_NAME='tcga_brca__MULTISURV'" in legacy
    assert "LABEL_FILE_PATH" not in legacy

    landmark = conf_text(
        study="tcga_brca",
        scheme="MULTISURV",
        modality="clinic_cox",
        clinic_dir=tmp_path / "clinic" / "landmark_0",
        split_dir=tmp_path / "splits",
        results_base=tmp_path / "results",
        landmark_tag="landmark_0",
        exp_group=analyzer_exp_group("landmark_0"),
        label_file=tmp_path / "labels" / "tcga_brca__landmark_0.csv",
    )
    assert "EXP_GROUP='A_manual_landmark/runs'" in landmark
    assert "RUN_NAME='tcga_brca__MULTISURV__landmark_0'" in landmark
    assert f"LABEL_FILE_PATH='{tmp_path / 'labels' / 'tcga_brca__landmark_0.csv'}'" in landmark
    # split dir untouched by the landmark arm
    assert f"SPLIT_DIR_PATH='{tmp_path / 'splits'}'" in landmark


def _touch_clinic_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _fake_label_stats(study: str, landmark_time, excluded: int = 7) -> dict:
    return {
        "study": study,
        "landmark_time_days": int(landmark_time),
        "apply_shift": True,
        "shift_months": landmark_time / (365.25 / 12),
        "cases_before": 100,
        "cases_after": 100 - excluded,
        "rows_before": 100,
        "rows_after": 100 - excluded,
        "event_rows_before": 50,
        "event_rows_after": 50 - excluded,
        "excluded_case_count": excluded,
        "excluded_cases": [],
    }


def test_iter_cindex_jobs_landmark_arm(tmp_path, monkeypatch):
    _load_scheme_fields()
    baseline_out = tmp_path / "outputs"
    legacy_dir = scheme_output_dir("TCGA-READ", "D0", str(baseline_out))
    masked_dir = scheme_output_dir("TCGA-READ", "D0", str(baseline_out), landmark_subdir="landmark_0")
    _touch_clinic_dir(legacy_dir)
    _touch_clinic_dir(masked_dir)

    label_file = tmp_path / "labels" / "tcga_read__landmark_0.csv"
    label_file.parent.mkdir(parents=True, exist_ok=True)
    label_file.write_text("case_id,survival_months,censorship\nTCGA-XX-0001,1.0,0\n", encoding="utf-8")
    calls = []

    def _fake_build(**kwargs):
        calls.append(kwargs)
        return label_file, _fake_label_stats(kwargs["study"], kwargs["landmark_time"])

    monkeypatch.setattr("src.cindex.build_landmark_label_file", _fake_build)

    datasets = {"TCGA-READ": {}}
    legacy_jobs = iter_cindex_jobs(
        dataset_name="TCGA-READ",
        schemes=["D0"],
        datasets=datasets,
        baseline_out=str(baseline_out),
        encoding="baseline",
        modalities="clinic_cox",
        results_root=tmp_path / "results",
    )
    assert len(legacy_jobs) == 1
    assert legacy_jobs[0]["clinic_dir"] == legacy_dir
    assert legacy_jobs[0]["label_file"] is None
    assert legacy_jobs[0]["row_scheme"] == "D0"
    assert legacy_jobs[0]["exp_group"] == "A_manual/runs"
    assert "A_manual/runs/tcga_read__D0/clinic_cox" in str(legacy_jobs[0]["out_dir"])
    assert calls == []  # landmark off -> no label surgery at all

    jobs = iter_cindex_jobs(
        dataset_name="TCGA-READ",
        schemes=["D0"],
        datasets=datasets,
        baseline_out=str(baseline_out),
        encoding="baseline",
        modalities="clinic_cox",
        results_root=tmp_path / "results",
        landmark_tag="landmark_0",
        landmark_time=0,
    )
    assert len(jobs) == 1
    job = jobs[0]
    assert calls == [{"study": "tcga_read", "landmark_time": 0, "results_root": tmp_path / "results", "apply_shift": True}]
    assert job["clinic_dir"] == masked_dir
    assert job["label_file"] == label_file
    assert job["row_scheme"] == "D0__landmark_0"
    assert job["run_name"] == "tcga_read__D0__landmark_0"
    assert job["exp_group"] == "A_manual_landmark/runs"
    assert job["conf_name"] == "tcga_read__D0__landmark_0__clinic_cox.conf"
    assert "A_manual_landmark/runs/tcga_read__D0__landmark_0/clinic_cox" in str(job["out_dir"])

    # landmark_none: legacy embedding dir, but the cindex table is the landmark one
    none_jobs = iter_cindex_jobs(
        dataset_name="TCGA-READ",
        schemes=["D0"],
        datasets=datasets,
        baseline_out=str(baseline_out),
        encoding="baseline",
        modalities="clinic_cox",
        results_root=tmp_path / "results",
        landmark_tag=LANDMARK_NONE_TAG,
    )
    assert none_jobs[0]["clinic_dir"] == legacy_dir
    assert none_jobs[0]["label_file"] is None
    assert calls == [{"study": "tcga_read", "landmark_time": 0, "results_root": tmp_path / "results", "apply_shift": True}]


def test_iter_cindex_jobs_shift_off_gets_own_run_name(tmp_path, monkeypatch):
    _load_scheme_fields()
    baseline_out = tmp_path / "outputs"
    _touch_clinic_dir(scheme_output_dir("TCGA-READ", "D0", str(baseline_out), landmark_subdir="landmark_365"))
    monkeypatch.setattr(
        "src.cindex.build_landmark_label_file",
        lambda **kwargs: (
            tmp_path / "labels.csv",
            _fake_label_stats(kwargs["study"], kwargs["landmark_time"], excluded=1),
        ),
    )
    jobs = iter_cindex_jobs(
        dataset_name="TCGA-READ",
        schemes=["D0"],
        datasets={"TCGA-READ": {}},
        baseline_out=str(baseline_out),
        encoding="baseline",
        modalities="clinic_cox",
        results_root=tmp_path / "results",
        landmark_tag="landmark_365",
        landmark_time=365,
        landmark_shift=False,
    )
    assert jobs[0]["row_scheme"] == "D0__landmark_365__noshift"
    assert jobs[0]["conf_name"] == "tcga_read__D0__landmark_365__noshift__clinic_cox.conf"
    # the embedding dir is the shifted arm's: only the label origin differs
    assert jobs[0]["clinic_dir"] == scheme_output_dir(
        "TCGA-READ", "D0", str(baseline_out), landmark_subdir="landmark_365"
    )


def test_summarize_dataset_writes_landmark_table(tmp_path):
    results_root = tmp_path / "results"
    out_dir = results_root / "A_manual_landmark" / "runs" / "tcga_read__L0__landmark_0" / "clinic_cox"
    out_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "val_cindex": [0.6, 0.7],
            "test_cindex": [0.5, 0.5],
        }
    ).to_csv(out_dir / "val_result_fold0.csv", index=False)
    jobs = [
        {
            "scheme": "L0",
            "row_scheme": "L0__landmark_0",
            "encoding": "prompt",
            "modality": "clinic_cox",
            "clinic_dir": tmp_path / "clinic",
            "out_dir": out_dir,
        }
    ]
    rows = summarize_dataset(
        dataset_name="TCGA-READ",
        jobs=jobs,
        results_root=results_root,
        encoding="text",
        modality="clinic_cox",
        landmark_tag="landmark_0",
    )
    assert [row["scheme"] for row in rows] == ["L0__landmark_0"]
    assert (results_root / "A_manual_landmark" / "TCGA-READ" / "cindex.csv").is_file()
    assert not (results_root / "A_manual").exists()


# --------------------------------------------------------------------------
# 5. label-side surgery: risk set + time origin
# --------------------------------------------------------------------------


def _write_label_csv(path: Path) -> Path:
    """4 patients: gt = 0, 12, 60, 120 months. 12 months = 365.25 days > 365."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["", "case_id", "slide_id", "survival_months", "censorship", "oncotree_code"])
        writer.writerow([0, "P0", "P0.svs", 0.0, 1, "IDC"])
        writer.writerow([1, "P12", "P12.svs", 12.0, 1, "IDC"])
        writer.writerow([2, "P60", "P60.svs", 60.0, 0, "IDC"])
        writer.writerow([3, "P120", "P120.svs", 120.0, 0, "IDC"])
    return path


def test_build_landmark_label_file_risk_set_and_shift(tmp_path):
    label_csv = _write_label_csv(tmp_path / "metadata" / "tcga_xx.csv")
    out_file, stats = build_landmark_label_file(
        study="tcga_xx",
        landmark_time=365,
        label_file=label_csv,
        out_path=tmp_path / "labels" / "tcga_xx__landmark_365.csv",
    )
    assert stats["cases_before"] == 4 and stats["cases_after"] == 3
    assert stats["excluded_cases"] == ["P0"]
    assert stats["excluded_rows"] == 1
    assert stats["event_rows_before"] == 2 and stats["event_rows_after"] == 2  # P60/P120
    assert stats["shift_months"] == pytest.approx(365 / (365.25 / 12))

    df = pd.read_csv(out_file)
    assert df["case_id"].tolist() == ["P12", "P60", "P120"]
    # time origin moved to T: 12 months (365.25d) -> 0.0082, 60 -> 48.0082, ...
    assert df["survival_months"].tolist() == pytest.approx([0.0082, 48.0082, 108.0082], abs=1e-3)
    assert df["censorship"].tolist() == [1, 0, 0]
    assert list(df.columns)[:3] == ["Unnamed: 0", "case_id", "slide_id"]
    assert (tmp_path / "labels" / "tcga_xx__landmark_365.json").is_file()


def test_build_landmark_label_file_shift_off_keeps_times(tmp_path):
    label_csv = _write_label_csv(tmp_path / "metadata" / "tcga_xx.csv")
    out_file, stats = build_landmark_label_file(
        study="tcga_xx",
        landmark_time=365,
        label_file=label_csv,
        out_path=tmp_path / "labels" / "tcga_xx__landmark_365__noshift.csv",
        apply_shift=False,
    )
    assert stats["apply_shift"] is False and stats["shift_months"] == 0.0
    df = pd.read_csv(out_file)
    assert df["case_id"].tolist() == ["P12", "P60", "P120"]
    assert df["survival_months"].tolist() == [12.0, 60.0, 120.0]


def test_build_landmark_label_file_at_zero_keeps_positive_times(tmp_path):
    label_csv = _write_label_csv(tmp_path / "metadata" / "tcga_xx.csv")
    out_file, stats = build_landmark_label_file(
        study="tcga_xx",
        landmark_time=0,
        label_file=label_csv,
        out_path=tmp_path / "labels" / "tcga_xx__landmark_0.csv",
    )
    assert stats["excluded_cases"] == ["P0"]
    df = pd.read_csv(out_file)
    assert df["survival_months"].tolist() == [12.0, 60.0, 120.0]  # shift of 0 months


def test_landmark_label_path_is_under_own_subtree(tmp_path):
    out_file, _ = build_landmark_label_file(
        study="tcga_xx",
        landmark_time=0,
        label_file=_write_label_csv(tmp_path / "metadata" / "tcga_xx.csv"),
        results_root=tmp_path / "results",
    )
    assert out_file == tmp_path / "results" / "A_manual_landmark" / "labels" / "tcga_xx__landmark_0.csv"


# --------------------------------------------------------------------------
# 6. CLI wiring
# --------------------------------------------------------------------------


def test_cli_rejects_landmark_time_for_hgcn_clinic(capsys):
    with pytest.raises(SystemExit) as exc:
        a_pipeline_main(["hgcn_clinic", "--dataset", "TCGA-READ", "--scheme", "L0", "--landmark_time", "0"])
    assert exc.value.code == 2
    assert "hgcn_clinic 不支持 --landmark_time" in capsys.readouterr().err


def test_cli_rejects_bad_landmark_time(capsys):
    with pytest.raises(SystemExit) as exc:
        a_pipeline_main(["json2prompt", "--dataset", "TCGA-READ", "--scheme", "L0", "--landmark_time", "abc"])
    assert exc.value.code == 2
    assert "--landmark_time" in capsys.readouterr().err


def test_cli_landmark_shift_choices(capsys):
    with pytest.raises(SystemExit) as exc:
        a_pipeline_main(["cindex", "--dataset", "TCGA-READ", "--scheme", "L0", "--landmark_shift", "maybe"])
    assert exc.value.code == 2
    assert "--landmark_shift" in capsys.readouterr().err


def test_cli_json2prompt_landmark_call(tmp_path):
    """CLI wiring: single-JSON mode writes into the landmark subdir."""
    _load_scheme_fields()
    json_path = _write_json_dir(tmp_path)
    prompt_root = tmp_path / "outputs" / "TCGA-KIRC" / "A_manual"
    a_pipeline_main(
        [
            "json2prompt",
            "--json_path",
            str(json_path),
            "--scheme",
            "MULTISURV",
            "--template_dir",
            DEFAULT_TEMPLATE_DIR,
            "--prompt_dir",
            str(prompt_root),
            "--landmark_time",
            "0",
        ]
    )
    assert (prompt_root / "MULTISURV" / "landmark_0" / "prompts.csv").is_file()
    assert not (prompt_root / "MULTISURV" / "prompts.csv").exists()

    # and the legacy call (no flag) keeps the legacy path
    a_pipeline_main(
        [
            "json2prompt",
            "--json_path",
            str(json_path),
            "--scheme",
            "MULTISURV",
            "--template_dir",
            DEFAULT_TEMPLATE_DIR,
            "--prompt_dir",
            str(prompt_root),
        ]
    )
    assert (prompt_root / "MULTISURV" / "prompts.csv").is_file()
