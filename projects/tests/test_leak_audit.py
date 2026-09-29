"""H1a 泄露审计单元测试：只用构造的小 JSON 病例，不碰真实数据、不跑 Clinic_Analyzer。"""

import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from leak.audit import (  # noqa: E402
    SUMMARY_COLUMNS,
    audit_dataset,
    audit_field,
    build_scheme_payload,
    load_scheme_fields,
    patient_landmark_states,
    resolve_audited_path,
    summarize_fields,
    summary_rows,
    write_summary_csv,
)


def _case(patient_id, stage=None, days_to_diagnosis=0, treatments=None, exposures=None):
    diagnosis = {"days_to_diagnosis": days_to_diagnosis}
    if stage is not None:
        diagnosis["ajcc_pathologic_stage"] = stage
    if treatments is not None:
        diagnosis["treatments"] = treatments
    case = {
        "submitter_id": patient_id,
        "project": {"project_id": "TCGA-SYNTH"},
        "demographic": {"vital_status": "Alive", "days_to_last_follow_up": 900, "age_at_index": 60},
        "diagnoses": [diagnosis],
    }
    if exposures is not None:
        case["exposures"] = exposures
    return case


def _stage_cases():
    """P1 诊断在 t0（0 天）、P2 诊断在 400 天（t0 之后）、P3 只有 sentinel 值。"""
    return [
        _case("P1", stage="Stage I", days_to_diagnosis=0),
        _case("P2", stage="Stage IV", days_to_diagnosis=400),
        _case("P3", stage="not reported", days_to_diagnosis=0),
    ]


def test_leak_rate_is_patient_ratio_masked_by_t0():
    cases = _stage_cases()
    states = patient_landmark_states(cases)
    row = audit_field(cases, states, "diagnoses[].ajcc_pathologic_stage")

    assert row["n_valid_none"] == 2      # P1 + P2 有有效值；P3 是 sentinel
    assert row["n_valid_t0"] == 1        # 只有 t0 内的 P1 保留
    assert row["leak_rate"] == 0.5
    assert row["leak_rate_undefined"] is False
    assert row["family"] == "diagnoses"
    assert row["mask_applicable"] is True
    assert row["audit_mode"] == "plain"


def test_untimed_field_is_never_affected_by_the_mask():
    cases = _stage_cases()
    states = patient_landmark_states(cases)
    row = audit_field(cases, states, "demographic.age_at_index")

    assert row["n_valid_none"] == 3
    assert row["n_valid_t0"] == 3
    assert row["leak_rate"] == 0.0
    assert row["mask_applicable"] is False


def test_project_id_is_constant_with_zero_leak():
    cases = _stage_cases()
    states = patient_landmark_states(cases)
    row = audit_field(cases, states, "project.project_id")

    assert row["audit_mode"] == "constant"
    assert row["n_valid_none"] == 3
    assert row["n_valid_t0"] == 3
    assert row["leak_rate"] == 0.0
    assert row["leak_rate_undefined"] is False


def test_derived_field_is_audited_on_its_underlying_slot():
    cases = [
        _case(
            "P1",
            days_to_diagnosis=0,
            treatments=[{"treatment_type": "radiation therapy, nos", "treatment_or_therapy": "Yes",
                         "days_to_treatment_start": 0}],
        ),
        _case(
            "P2",
            days_to_diagnosis=0,
            treatments=[{"treatment_type": "radiation therapy, nos", "treatment_or_therapy": "Yes",
                         "days_to_treatment_start": 300}],
        ),
    ]
    states = patient_landmark_states(cases)
    derived = audit_field(cases, states, "derived.radiation_therapy")
    source = audit_field(cases, states, "diagnoses[].treatments[].treatment_or_therapy")

    assert resolve_audited_path("derived.radiation_therapy") == (
        "diagnoses[].treatments[].treatment_or_therapy",
        "derived_slot",
    )
    assert derived["audit_mode"] == "derived_slot"
    assert derived["audited_path"] == "diagnoses[].treatments[].treatment_or_therapy"
    assert derived["family"] == "diagnoses_treatments"
    assert derived["n_valid_none"] == source["n_valid_none"] == 2
    assert derived["n_valid_t0"] == source["n_valid_t0"]
    assert derived["leak_rate"] == source["leak_rate"]


def test_derived_field_with_untimed_source_has_zero_leak():
    cases = [_case("P1", exposures=[{"exposure_duration_years": 12}])]
    states = patient_landmark_states(cases)
    row = audit_field(cases, states, "derived.years_smoked")

    assert row["audited_path"] == "exposures[].exposure_duration_years"
    assert row["family"] is None
    assert row["mask_applicable"] is False
    assert row["n_valid_none"] == 1
    assert row["leak_rate"] == 0.0


def test_no_valid_values_yields_nan_and_flag():
    cases = _stage_cases()
    states = patient_landmark_states(cases)
    row = audit_field(cases, states, "exposures[].cigarettes_per_day")

    assert row["n_valid_none"] == 0
    assert math.isnan(row["leak_rate"])
    assert row["leak_rate_undefined"] is True

    summary = summarize_fields(
        [
            row,
            {
                "leak_rate": 0.25,
                "leak_rate_undefined": False,
                "not_in_bank": False,
            },
        ]
    )
    assert summary["n_fields"] == 2
    assert summary["n_leak_rate_undefined"] == 1
    # NaN 不进 mean
    assert summary["mean_leak_rate"] == 0.25
    assert summary["n_leaky"] == 1
    assert summary["leaky_ratio"] == 0.5


def test_not_in_bank_marking_uses_kept_fields():
    fields = ["demographic.age_at_index", "project.project_id"]
    payloads = audit_dataset(
        "TCGA-SYNTH",
        _stage_cases(),
        ["FAKE"],
        {"FAKE": fields},
        kept_fields={"demographic.age_at_index"},
    )
    payload = payloads[0]
    rows = {row["field"]: row for row in payload["fields"]}

    assert rows["demographic.age_at_index"]["not_in_bank"] is False
    assert rows["project.project_id"]["not_in_bank"] is True
    assert payload["kept_fields_available"] is True
    assert payload["n_not_in_bank"] == 1

    no_bank = build_scheme_payload(
        "TCGA-SYNTH", "FAKE", list(rows.values()), kept_fields=None, n_patients=3
    )
    assert no_bank["kept_fields_available"] is False
    assert all(row["not_in_bank"] is False for row in no_bank["fields"])


def test_scheme_fields_are_read_from_templates_json(tmp_path):
    scheme_dir = tmp_path / "FAKE"
    scheme_dir.mkdir()
    (scheme_dir / "fields.json").write_text(
        json.dumps({"description": "fake", "fields": ["b", "a", "b", ""]}),
        encoding="utf-8",
    )
    assert load_scheme_fields("FAKE", tmp_path) == ["b", "a"]


def test_summary_csv_joins_event_counts(tmp_path):
    payloads = audit_dataset(
        "TCGA-SYNTH",
        _stage_cases(),
        ["FAKE"],
        {"FAKE": ["demographic.age_at_index", "diagnoses[].ajcc_pathologic_stage"]},
        kept_fields=None,
    )
    events = {"TCGA-SYNTH": {"n_event": "42", "event_rate": "0.2500"}}
    rows = summary_rows(payloads, events)

    assert len(rows) == 1
    row = rows[0]
    assert row["dataset"] == "TCGA-SYNTH"
    assert row["scheme"] == "FAKE"
    assert row["n_fields"] == 2
    assert row["n_leaky"] == 1
    assert row["leaky_ratio"] == "0.500000"
    assert row["n_event"] == "42"
    assert row["event_rate"] == "0.2500"

    out = write_summary_csv(tmp_path / "nested" / "leak_audit_summary.csv", rows)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == ",".join(SUMMARY_COLUMNS)
    assert "TCGA-SYNTH,FAKE,2,1,0.500000" in lines[1]


def test_cli_writes_per_dataset_json_and_summary(tmp_path, monkeypatch):
    clinic_path = tmp_path / "synthetic_cases.json"
    clinic_path.write_text(json.dumps(_stage_cases()), encoding="utf-8")
    datasets_path = tmp_path / "datasets.json"
    datasets_path.write_text(
        json.dumps({"TCGA-SYNTH": {"clinic_files": [str(clinic_path)], "project_ids": []}}),
        encoding="utf-8",
    )
    templates_root = tmp_path / "templates"
    (templates_root / "FAKE").mkdir(parents=True)
    (templates_root / "FAKE" / "fields.json").write_text(
        json.dumps({"fields": ["diagnoses[].ajcc_pathologic_stage", "project.project_id"]}),
        encoding="utf-8",
    )
    event_summary = tmp_path / "event_summary.csv"
    event_summary.write_text(
        "dataset,n_patients,n_event,n_censored,n_unknown,event_rate\n"
        "TCGA-SYNTH,3,1,2,0,0.3333\n",
        encoding="utf-8",
    )

    from leak import audit as audit_module
    from leak.cli import main

    monkeypatch.setattr(
        audit_module, "load_kept_fields_set", lambda name: {"project.project_id"}
    )

    out_dir = tmp_path / "leak_audit"
    code = main(
        [
            "--datasets_config",
            str(datasets_path),
            "--dataset",
            "all",
            "--schemes",
            "FAKE",
            "--templates_root",
            str(templates_root),
            "--out_dir",
            str(out_dir),
            "--event_summary",
            str(event_summary),
            "--quiet",
        ]
    )
    assert code == 0

    payload = json.loads((out_dir / "TCGA-SYNTH" / "FAKE.json").read_text(encoding="utf-8"))
    rows = {row["field"]: row for row in payload["fields"]}
    assert payload["kept_fields_available"] is True
    assert payload["n_patients"] == 3
    assert rows["diagnoses[].ajcc_pathologic_stage"]["leak_rate"] == 0.5
    assert rows["diagnoses[].ajcc_pathologic_stage"]["not_in_bank"] is True
    assert rows["project.project_id"]["not_in_bank"] is False

    csv_lines = (out_dir / "leak_audit_summary.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(csv_lines) == 2
    assert csv_lines[1].startswith("TCGA-SYNTH,FAKE,2,1,")
    assert csv_lines[1].endswith(",1,0.3333")
