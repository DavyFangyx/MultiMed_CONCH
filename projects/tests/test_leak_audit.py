"""Test_1a 泄露审计单元测试：只用构造的小 JSON 病例，不碰真实数据、不跑 Clinic_Analyzer。"""

import json
import math
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from leak.audit import (  # noqa: E402
    BINDING_ALL,
    BINDING_SPEC,
    EXCLUDED_DATASETS,
    HGCN_DATASET_BY_SCHEME,
    LEAK_SCHEMES,
    PAN_CANCER_SCHEMES,
    SUMMARY_COLUMNS,
    audit_dataset,
    audit_field,
    build_audit_plan,
    build_scheme_payload,
    load_scheme_fields,
    patient_landmark_states,
    plan_datasets,
    plan_schemes,
    prune_stale_outputs,
    resolve_audited_path,
    scheme_dataset_binding,
    summarize_fields,
    summary_rows,
    tcga_dataset_names,
    write_summary_csv,
)

# 33 个 TCGA 注册队列的最小合成表：6 个 HGCN 绑定癌种 + 27 个占位队列
_HGCN_CANCERS = ["TCGA-KIRC", "TCGA_LIHC", "TCGA-ESCA", "TCGA-LUSC", "TCGA-LUAD", "TCGA-UCEC"]


def _registry_33_tcga():
    return _HGCN_CANCERS + [f"TCGA-T{index:02d}" for index in range(27)]


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


def test_hgcn_schemes_are_bound_to_their_own_cancer():
    registry = _registry_33_tcga()
    # spec §2.4：六方案各绑定一个癌种；TCGA_LIHC 注册名是下划线
    assert HGCN_DATASET_BY_SCHEME == {
        "HGCN_KIRC": "TCGA-KIRC",
        "HGCN_LIHC": "TCGA_LIHC",
        "HGCN_ESCA": "TCGA-ESCA",
        "HGCN_LUSC": "TCGA-LUSC",
        "HGCN_LUAD": "TCGA-LUAD",
        "HGCN_UCEC": "TCGA-UCEC",
    }
    for scheme, dataset in HGCN_DATASET_BY_SCHEME.items():
        binding = scheme_dataset_binding(scheme, registry)
        assert binding["kind"] == "hgcn_cancer"
        assert binding["datasets"] == [dataset]

    # HGCN_LUSC 只允许 TCGA-LUSC：禁止塞进其他癌种
    plan = build_audit_plan(registry, ["HGCN_LUSC"], binding=BINDING_SPEC)
    assert plan == [("TCGA-LUSC", "HGCN_LUSC")]
    assert [name for name, _ in plan] == ["TCGA-LUSC"]

    # 绑定癌种没被注册/剔除时直接报错，不静默降级
    with pytest.raises(ValueError):
        scheme_dataset_binding("HGCN_LUSC", [name for name in registry if name != "TCGA-LUSC"])
    with pytest.raises(ValueError):
        build_audit_plan(["CPTAC"], ["HGCN_LUSC"], binding=BINDING_SPEC)


def test_pan_cancer_schemes_cover_all_33_tcga():
    registry = _registry_33_tcga()
    assert sorted(PAN_CANCER_SCHEMES) == sorted(
        set(LEAK_SCHEMES) - set(HGCN_DATASET_BY_SCHEME)
    )
    for scheme in PAN_CANCER_SCHEMES:
        binding = scheme_dataset_binding(scheme, registry)
        assert binding["kind"] == "pan_cancer"
        assert binding["datasets"] == sorted(registry)
        assert len(binding["datasets"]) == 33

    # 未在 §2.4 登记的方案不静默当成绑定方案，按泛癌种处理但标 pan_cancer_default
    assert scheme_dataset_binding("FAKE", registry)["kind"] == "pan_cancer_default"


def test_cptac_and_mmrf_are_never_in_scope():
    registry = _registry_33_tcga() + ["CPTAC", "MMRF"]
    assert EXCLUDED_DATASETS == ("CPTAC", "MMRF")
    assert tcga_dataset_names(registry) == sorted(_registry_33_tcga())
    # 非 TCGA 前缀的队列（无论是否在排除集里）都进不来
    assert tcga_dataset_names(["TCGA-ACC", "FAKE-EXT", "CPTAC", "MMRF"]) == ["TCGA-ACC"]

    for binding in (BINDING_SPEC, BINDING_ALL):
        plan = build_audit_plan(registry, LEAK_SCHEMES, binding=binding)
        datasets = {name for name, _ in plan}
        assert "CPTAC" not in datasets
        assert "MMRF" not in datasets


def test_audit_plan_is_4x33_plus_6():
    registry = _registry_33_tcga() + ["CPTAC", "MMRF"]
    plan = build_audit_plan(registry, LEAK_SCHEMES, binding=BINDING_SPEC)

    assert len(plan) == 4 * 33 + 6 == 138
    assert len(set(plan)) == len(plan)  # 无重复组合
    assert plan_datasets(plan) == sorted(_registry_33_tcga())
    assert sorted(plan_schemes(plan)) == sorted(LEAK_SCHEMES)
    for scheme, dataset in plan:
        if scheme in HGCN_DATASET_BY_SCHEME:                    # HGCN_* 只有本癌种
            assert dataset == HGCN_DATASET_BY_SCHEME[scheme]
    assert len([item for item in plan if item[1] == "HGCN_UCEC"]) == 1

    # all 模式 = 10 × 33（放宽方案绑定，但外部数据集仍剔除）
    plan_all = build_audit_plan(registry, LEAK_SCHEMES, binding=BINDING_ALL)
    assert len(plan_all) == 10 * 33 == 330


def test_prune_removes_unplanned_json_and_empty_dataset_dirs(tmp_path):
    out_root = tmp_path / "leak_audit"
    for dataset, scheme in (
        ("TCGA-KIRC", "HGCN_KIRC"),
        ("TCGA-KIRC", "HGCN_LUSC"),  # 旧错误绑定：跨癌种
        ("CPTAC", "SURVPGC"),        # 旧错误绑定：外部数据集
    ):
        path = out_root / dataset / f"{scheme}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    (out_root / "leak_audit_summary.csv").write_text("dataset,scheme\n", encoding="utf-8")

    removed = prune_stale_outputs(out_root, [("TCGA-KIRC", "HGCN_KIRC")])

    assert sorted(removed) == ["CPTAC/", "CPTAC/SURVPGC.json", "TCGA-KIRC/HGCN_LUSC.json"]
    assert (out_root / "TCGA-KIRC" / "HGCN_KIRC.json").exists()
    assert not (out_root / "TCGA-KIRC" / "HGCN_LUSC.json").exists()
    assert not (out_root / "CPTAC").exists()
    assert (out_root / "leak_audit_summary.csv").exists()  # 汇总表不归 prune 管


def test_payload_records_the_binding(tmp_path):
    registry = _registry_33_tcga() + ["CPTAC", "MMRF"]
    binding = scheme_dataset_binding("HGCN_LUSC", registry)
    payload = build_scheme_payload(
        "TCGA-LUSC",
        "HGCN_LUSC",
        [{"field": "x", "leak_rate": 0.0, "leak_rate_undefined": False, "not_in_bank": False}],
        kept_fields=None,
        n_patients=3,
        binding=binding,
    )
    assert payload["scheme_binding"] == "hgcn_cancer"
    assert payload["binding_datasets"] == ["TCGA-LUSC"]


def test_template_datasets_key_does_not_drive_the_binding(tmp_path, monkeypatch):
    """绑定只在 src/leak 声明；templates/fields.json 的 datasets 键（旧全绑定）必须被忽略。"""
    clinic_path = tmp_path / "synthetic_cases.json"
    clinic_path.write_text(json.dumps(_stage_cases()), encoding="utf-8")
    registry = ["TCGA-LUSC", "TCGA-KIRC", "CPTAC", "MMRF"]
    datasets_path = tmp_path / "datasets.json"
    datasets_path.write_text(
        json.dumps({name: {"clinic_files": [str(clinic_path)]} for name in registry}),
        encoding="utf-8",
    )
    templates_root = tmp_path / "templates"
    (templates_root / "HGCN_LUSC").mkdir(parents=True)
    (templates_root / "HGCN_LUSC" / "fields.json").write_text(
        json.dumps(
            {
                "fields": ["diagnoses[].ajcc_pathologic_stage"],
                # 旧字段表把方案全绑定到所有队列——必须不影响范围
                "datasets": ["TCGA-LUSC", "TCGA-KIRC", "CPTAC", "MMRF"],
            }
        ),
        encoding="utf-8",
    )
    (templates_root / "MULTISURV").mkdir(parents=True)
    (templates_root / "MULTISURV" / "fields.json").write_text(
        json.dumps({"fields": ["demographic.age_at_index"], "datasets": []}),
        encoding="utf-8",
    )

    from leak import audit as audit_module
    from leak.cli import main

    monkeypatch.setattr(audit_module, "load_kept_fields_set", lambda name: None)

    out_dir = tmp_path / "leak_audit"
    code = main(
        [
            "--datasets_config", str(datasets_path),
            "--dataset", "all",
            "--schemes", "HGCN_LUSC,MULTISURV",
            "--templates_root", str(templates_root),
            "--out_dir", str(out_dir),
            "--quiet",
        ]
    )
    assert code == 0

    produced = sorted(
        f"{path.parent.name}/{path.name}" for path in out_dir.glob("*/*.json")
    )
    assert produced == [
        "TCGA-KIRC/MULTISURV.json",
        "TCGA-LUSC/HGCN_LUSC.json",
        "TCGA-LUSC/MULTISURV.json",
    ]
    assert not (out_dir / "CPTAC").exists()
    assert not (out_dir / "MMRF").exists()

    payload = json.loads((out_dir / "TCGA-LUSC" / "HGCN_LUSC.json").read_text(encoding="utf-8"))
    assert payload["binding_datasets"] == ["TCGA-LUSC"]
    assert payload["scheme_binding"] == "hgcn_cancer"

    summary = (out_dir / "leak_audit_summary.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(summary) == 4  # 表头 + 3 个组合
    assert all("CPTAC" not in line and "MMRF" not in line for line in summary[1:])


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
