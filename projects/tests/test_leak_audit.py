"""Test_2a 泄露审计单元测试（新口径，spec §2.1）：只用构造的小 JSON 病例，不碰真实数据、不跑 Clinic_Analyzer。

口径：
``leak_rate = #{值来源槽位 t_hi > 0 / lo_only} / #{管线产出有效值}``，
取值走 ``A_pipeline/src/extract.py::extract_values``（无泄露处理），
来源槽位时点走 ``src/time_stats.py`` 的 ``t_hi``（point/bounded 有限 t_hi、lo_only = +∞、
unlocated/non_informative 无 t_hi）。
"""

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
    build_g1_payload,
    build_scheme_payload,
    g1_scheme_name,
    load_kept_fields_list,
    load_scheme_fields,
    plan_datasets,
    plan_schemes,
    prune_stale_outputs,
    scheme_dataset_binding,
    summarize_fields,
    summary_rows,
    tcga_dataset_names,
    write_summary_csv,
)
from leak.provenance import (  # noqa: E402
    MODE_A_PIPELINE,
    MODE_FIELD_BANK,
    a_pipeline_field_names,
    a_pipeline_spec,
    audited_slot_path,
    case_contexts,
    field_provenance,
)

# 33 个 TCGA 注册队列的最小合成表：6 个 HGCN 绑定癌种 + 27 个占位队列
_HGCN_CANCERS = ["TCGA-KIRC", "TCGA_LIHC", "TCGA-ESCA", "TCGA-LUSC", "TCGA-LUAD", "TCGA-UCEC"]

STAGE_FIELD = "diagnoses[].ajcc_pathologic_stage"       # A_pipeline 取值表内（diagnoses 家族）
AGE_FIELD = "demographic.age_at_index"                  # 无时点家族
THERAPY_FIELD = "derived.radiation_therapy"             # derived.* → 追底层 treatment 槽位
BANK_ONLY_FIELD = "diagnoses[].tumor_of_origin"         # 不在 A_pipeline 取值表（Field Bank 口径）


def _registry_33_tcga():
    return _HGCN_CANCERS + [f"TCGA-T{index:02d}" for index in range(27)]


def _case(
    patient_id,
    *,
    stage=None,
    days_to_diagnosis=0,
    treatments=None,
    exposures=None,
    follow_up_days=None,
    age=60,
    no_diagnosis_days=False,
):
    """合成病例：days_to_diagnosis=0 → 槽位 (0,0] point；>0 + 有锚点 → bounded。

    锚点（days_to_last_follow_up，TH2）缺失时 >0 的诊断槽位是 lo_only（t_hi = +∞）。
    """
    diagnosis = {}
    if not no_diagnosis_days:
        diagnosis["days_to_diagnosis"] = days_to_diagnosis
    if stage is not None:
        diagnosis["ajcc_pathologic_stage"] = stage
    if treatments is not None:
        diagnosis["treatments"] = treatments
    if follow_up_days is not None:
        diagnosis["days_to_last_follow_up"] = follow_up_days
    case = {
        "submitter_id": patient_id,
        "project": {"project_id": "TCGA-SYNTH"},
        "demographic": {"vital_status": "Alive", "age_at_index": age},
        "diagnoses": [diagnosis],
    }
    if exposures is not None:
        case["exposures"] = exposures
    return case


def _contexts(cases):
    return case_contexts(cases)


def _row(cases, field):
    return audit_field(_contexts(cases), field)


# --------------------------------------------------------------------------- 新口径核心判据
def test_value_from_future_slot_leaks():
    """P2 的诊断槽位 (100, 300] → t_hi = 300 > 0 → 泄露；P1 的 (0, 0] → 不泄露。"""
    cases = [
        _case("P1", stage="Stage I", days_to_diagnosis=0),
        _case("P2", stage="Stage IV", days_to_diagnosis=100, follow_up_days=300),
    ]
    row = _row(cases, STAGE_FIELD)

    assert row["family"] == "diagnoses"
    assert row["audit_mode"] == MODE_A_PIPELINE
    assert row["n_valid"] == 2                      # 两例都有有效 stage
    assert row["n_leak"] == 1                       # 只有 P2 的值来自 t_hi > 0 的槽位
    assert row["leak_rate"] == 0.5
    assert row["leak_rate_undefined"] is False
    assert row["source_slot_families"] == ["diagnoses"]
    assert row["source_slot_statuses"] == ["bounded"]
    assert row["max_source_t_hi"] == 300.0
    assert row["n_unlocated_source"] == 0


def test_value_from_t0_slot_does_not_leak():
    """t_hi = 0（point 槽位）不算泄露——判据是严格 t_hi > 0。"""
    cases = [_case("P1", stage="Stage I"), _case("P2", stage="Stage II")]
    row = _row(cases, STAGE_FIELD)

    assert row["n_valid"] == 2
    assert row["n_leak"] == 0
    assert row["leak_rate"] == 0.0
    assert row["max_source_t_hi"] is None


def test_absolute_rate_below_old_definition():
    """旧口径（t0 丢值比例）会给出 1.0；新口径只看"值来源是否未来"，P1 不泄露。"""
    cases = [
        _case("P1", stage="Stage I", days_to_diagnosis=0),          # t0 有值
        _case("P2", stage="Stage IV", days_to_diagnosis=100, follow_up_days=300),
        _case("P3", stage="Stage III", days_to_diagnosis=200, follow_up_days=300),
    ]
    row = _row(cases, STAGE_FIELD)

    assert row["n_valid"] == 3
    assert row["n_leak"] == 2
    assert abs(row["leak_rate"] - 2.0 / 3.0) < 1e-12


def test_denominator_is_pipeline_valid_values_only():
    """分母 = 管线产出有效值的患者（占位符 Stage X 不进入分子分母）。"""
    cases = [
        _case("P1", stage="Stage I", days_to_diagnosis=0),
        _case("P2", stage="Stage IV", days_to_diagnosis=100, follow_up_days=300),
        _case("P3", stage="Stage X", days_to_diagnosis=100, follow_up_days=300),  # 占位符
    ]
    row = _row(cases, STAGE_FIELD)

    assert row["n_patients"] == 3
    assert row["n_valid"] == 2          # P3 的 Stage X 是占位符
    assert row["n_leak"] == 1
    assert row["leak_rate"] == 0.5      # 而不是 2/3


def test_untimed_family_never_leaks():
    """demographic 无时点家族：值不来自任何槽位，恒不泄露（n_no_source 记录这一点）。"""
    cases = [_case("P1"), _case("P2", days_to_diagnosis=400, follow_up_days=900)]
    row = _row(cases, AGE_FIELD)

    assert row["family"] is None
    assert row["audit_mode"] == MODE_A_PIPELINE
    assert row["n_valid"] == 2
    assert row["n_leak"] == 0
    assert row["leak_rate"] == 0.0
    assert row["n_no_source"] == 2


def test_lo_only_source_leaks():
    """lo_only（t_hi = +∞，上界失守）按 time_axis.md §4.1 判泄露，单列 n_lo_only_source。"""
    cases = [_case("P1", stage="Stage I"), _case("P2", stage="Stage IV", days_to_diagnosis=100)]
    row = _row(cases, STAGE_FIELD)

    assert row["n_valid"] == 2
    assert row["n_leak"] == 1
    assert row["n_lo_only_source"] == 1
    assert row["source_slot_statuses"] == ["lo_only"]
    assert row["max_source_t_hi"] is None       # +∞ 不写有限值
    assert row["n_unlocated_source"] == 0


def test_unlocated_source_is_not_a_leak_but_is_reported():
    """unlocated（无 t_hi）无法断言未来：不计入 leak_rate，但单列并计入 n_t0_blocked。"""
    cases = [_case("P1", stage="Stage I", no_diagnosis_days=True)]
    row = _row(cases, STAGE_FIELD)

    assert row["n_valid"] == 1
    assert row["n_leak"] == 0
    assert row["leak_rate"] == 0.0
    assert row["n_unlocated_source"] == 1
    assert row["n_t0_blocked"] == 1


def test_no_valid_values_yields_nan_and_flag():
    cases = [_case("P1", stage="Stage X"), _case("P2", stage="Stage X")]
    row = _row(cases, "exposures[].cigarettes_per_day")

    assert row["n_valid"] == 0
    assert math.isnan(row["leak_rate"])
    assert row["leak_rate_undefined"] is True

    summary = summarize_fields(
        [
            row,
            {"leak_rate": 0.25, "leak_rate_undefined": False, "n_leak": 1, "n_valid": 4,
             "n_t0_blocked": 2, "audit_mode": MODE_A_PIPELINE, "not_in_bank": False},
        ]
    )
    assert summary["n_fields"] == 2
    assert summary["n_leak_rate_undefined"] == 1
    assert summary["mean_leak_rate"] == 0.25     # NaN 不进 mean
    assert summary["n_leaky"] == 1
    assert summary["leaky_ratio"] == 0.5
    assert summary["n_leak_total"] == 1
    assert summary["n_valid_total"] == 4


# --------------------------------------------------------------------------- derived.* / 模式
def test_derived_therapy_traces_underlying_treatment_slots():
    """derived.radiation_therapy 的来源是匹配 treatment_type 的治疗槽位（不是源路径 raw 值）。"""
    cases = [
        _case("P1", treatments=[{"treatment_type": "radiation therapy, nos",
                                 "treatment_or_therapy": "Yes", "days_to_treatment_start": 0}]),
        _case("P2", follow_up_days=300,
              treatments=[{"treatment_type": "radiation therapy, nos",
                           "treatment_or_therapy": "Yes", "days_to_treatment_start": 100}]),
    ]
    row = _row(cases, THERAPY_FIELD)

    assert row["audit_mode"] == MODE_A_PIPELINE
    assert row["audited_path"] == audited_slot_path(THERAPY_FIELD)
    assert row["audited_path"] == "diagnoses[].treatments[].treatment_or_therapy"
    assert row["family"] == "diagnoses_treatments"
    assert row["n_valid"] == 2          # 两例都给 "yes"
    assert row["n_leak"] == 1           # P2 的治疗槽位 t_hi = 300（TH2 锚点）
    assert row["source_slot_families"] == ["diagnoses_treatments"]

    # 阴性治疗（treatment_or_therapy = No）不建槽 → 该来源为"无时点来源"，不泄露
    negative = [_case("P3", treatments=[{"treatment_type": "radiation therapy, nos",
                                         "treatment_or_therapy": "No",
                                         "days_to_treatment_start": 400}])]
    neg_row = _row(negative, THERAPY_FIELD)
    assert neg_row["n_valid"] == 1
    assert neg_row["n_leak"] == 0
    assert neg_row["n_untimed_source"] == 1


def test_derived_years_smoked_with_untimed_source_never_leaks():
    cases = [_case("P1", exposures=[{"exposure_duration_years": 12}])]
    row = _row(cases, "derived.years_smoked")

    assert row["audited_path"] == "exposures[].exposure_duration_years"
    assert row["family"] is None
    assert row["n_valid"] == 1
    assert row["n_leak"] == 0
    assert row["n_untimed_source"] == 1


def test_field_bank_mode_is_used_outside_the_pipeline_universe():
    """不在 A_pipeline extract_values 取值表内的字段走 Field Bank 口径（值 + 来源同规则）。"""
    assert a_pipeline_spec(BANK_ONLY_FIELD) is None
    assert BANK_ONLY_FIELD not in a_pipeline_field_names()

    cases = [
        _case("P1", days_to_diagnosis=0),
        _case("P2", days_to_diagnosis=100, follow_up_days=300),
    ]
    for case, origin in zip(cases, ("Breast", "Breast")):
        case["diagnoses"][0]["tumor_of_origin"] = origin
    row = _row(cases, BANK_ONLY_FIELD)

    assert row["audit_mode"] == MODE_FIELD_BANK
    assert row["n_valid"] == 2
    assert row["n_leak"] == 1
    assert row["leak_rate"] == 0.5
    assert row["source_slot_families"] == ["diagnoses"]


def test_pipeline_value_is_the_one_actually_used():
    """审计取值必须等于 A_pipeline extract_values 的取值（sex 回退 gender、占位符一致）。"""
    case = _case("P1")
    case["demographic"].pop("age_at_index")
    case["demographic"]["gender"] = "female"
    ctx = case_contexts([case])[0]

    assert ctx.values["demographic.sex_at_birth"] == "female"
    item = field_provenance("demographic.sex_at_birth", ctx)
    assert item.value == "female" and item.valid is True

    missing = case_contexts([_case("P2")])[0]
    assert field_provenance("demographic.race", missing).value == "not reported"
    assert field_provenance("demographic.race", missing).valid is False


# --------------------------------------------------------------------------- 产物 schema
def test_not_in_bank_marking_uses_kept_fields():
    fields = [AGE_FIELD, "project.project_id"]
    payloads, _ = audit_dataset(
        "TCGA-SYNTH",
        [_case("P1")],
        ["FAKE"],
        {"FAKE": fields},
        kept_field_list=[AGE_FIELD],
    )
    payload = payloads[0]
    rows = {row["field"]: row for row in payload["fields"]}

    assert rows[AGE_FIELD]["not_in_bank"] is False
    assert rows["project.project_id"]["not_in_bank"] is True
    assert payload["kept_fields_available"] is True
    assert payload["n_not_in_bank"] == 1
    assert payload["leak_definition"] == "value_provenance: source slot t_hi > 0"

    no_bank = build_scheme_payload(
        "TCGA-SYNTH", "FAKE", list(rows.values()), kept_fields=None, n_patients=1
    )
    assert no_bank["kept_fields_available"] is False
    assert all(row["not_in_bank"] is False for row in no_bank["fields"])


def test_g1_payload_schema_matches_test_1a_consumer():
    """G1 单字段产物：schema 对齐 results_display/scripts/Test_1a_field_level.py::load_leak_rates。"""
    cases = [
        _case("P1", stage="Stage I", days_to_diagnosis=0),
        _case("P2", stage="Stage IV", days_to_diagnosis=100, follow_up_days=300),
    ]
    row = _row(cases, STAGE_FIELD)
    payload = build_g1_payload("TCGA-SYNTH", 4, row, n_patients=2)

    assert payload["scheme"] == g1_scheme_name(4)
    assert payload["scheme"].startswith("G1_") and len(payload["scheme"]) == 13
    assert payload["field_idx"] == 4
    assert payload["field"] == STAGE_FIELD
    assert payload["leak_rate"] == 0.5
    assert payload["leak_rate_undefined"] is False
    items = {item["field"]: item for item in payload["fields"]}
    assert items[STAGE_FIELD]["leak_rate"] == 0.5
    assert items[STAGE_FIELD]["family"] == "diagnoses"

    # field_idx → scheme 名与贪心侧同一实现
    from greedy.embeddings import subset_scheme_name

    assert g1_scheme_name(4) == subset_scheme_name([4])


def test_audit_dataset_returns_scheme_and_g1_payloads():
    fields = {"FAKE": [STAGE_FIELD]}
    payloads, g1 = audit_dataset(
        "TCGA-SYNTH",
        [_case("P1", stage="Stage I")],
        ["FAKE"],
        fields,
        kept_field_list=[STAGE_FIELD, "diagnoses[].tumor_of_origin"],
    )
    assert len(payloads) == 1 and len(g1) == 2
    assert [item["field_idx"] for item in g1] == [0, 1]
    assert g1[1]["field"] == "diagnoses[].tumor_of_origin"
    assert g1[1]["leak_rate_undefined"] is True     # 合成病例无该字段 → 分母 0
    assert math.isnan(g1[1]["leak_rate"])


# --------------------------------------------------------------------------- 绑定与计划（范围）
def test_hgcn_schemes_are_bound_to_their_own_cancer():
    registry = _registry_33_tcga()
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

    plan = build_audit_plan(registry, ["HGCN_LUSC"], binding=BINDING_SPEC)
    assert plan == [("TCGA-LUSC", "HGCN_LUSC")]

    with pytest.raises(ValueError):
        scheme_dataset_binding("HGCN_LUSC", [name for name in registry if name != "TCGA-LUSC"])
    with pytest.raises(ValueError):
        build_audit_plan(["CPTAC"], ["HGCN_LUSC"], binding=BINDING_SPEC)


def test_single_dataset_run_resolves_binding_against_full_registry():
    """--dataset 单队列时，绑定仍按注册表全表解析（否则 HGCN_* 会误报"不在注册表"）。"""
    registry = _registry_33_tcga()
    plan = build_audit_plan(["TCGA-LUSC"], ["HGCN_LUSC", "MULTISURV"], registry=registry)
    assert plan == [("TCGA-LUSC", "HGCN_LUSC"), ("TCGA-LUSC", "MULTISURV")]
    # 未传 registry 时退回用 dataset_names（单个队列 → 只有该队列自己的方案）
    assert build_audit_plan(["TCGA-LUSC"], ["MULTISURV"]) == [("TCGA-LUSC", "MULTISURV")]


def test_pan_cancer_schemes_cover_all_33_tcga():
    registry = _registry_33_tcga()
    assert sorted(PAN_CANCER_SCHEMES) == sorted(set(LEAK_SCHEMES) - set(HGCN_DATASET_BY_SCHEME))
    for scheme in PAN_CANCER_SCHEMES:
        binding = scheme_dataset_binding(scheme, registry)
        assert binding["kind"] == "pan_cancer"
        assert binding["datasets"] == sorted(registry)
        assert len(binding["datasets"]) == 33
    assert scheme_dataset_binding("FAKE", registry)["kind"] == "pan_cancer_default"


def test_cptac_and_mmrf_are_never_in_scope():
    registry = _registry_33_tcga() + ["CPTAC", "MMRF"]
    assert EXCLUDED_DATASETS == ("CPTAC", "MMRF")
    assert tcga_dataset_names(registry) == sorted(_registry_33_tcga())
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
    assert len(set(plan)) == len(plan)
    assert sorted(plan_datasets(plan)) == sorted(_registry_33_tcga())
    assert sorted(plan_schemes(plan)) == sorted(LEAK_SCHEMES)
    for scheme, dataset in plan:
        if scheme in HGCN_DATASET_BY_SCHEME:
            assert dataset == HGCN_DATASET_BY_SCHEME[scheme]
    assert len([item for item in plan if item[1] == "HGCN_UCEC"]) == 1

    plan_all = build_audit_plan(registry, LEAK_SCHEMES, binding=BINDING_ALL)
    assert len(plan_all) == 10 * 33 == 330


def test_scheme_fields_are_read_from_templates_json(tmp_path):
    scheme_dir = tmp_path / "FAKE"
    scheme_dir.mkdir()
    (scheme_dir / "fields.json").write_text(
        json.dumps({"description": "fake", "fields": ["b", "a", "b", ""]}),
        encoding="utf-8",
    )
    assert load_scheme_fields("FAKE", tmp_path) == ["b", "a"]


def test_load_kept_fields_list_preserves_order(tmp_path, monkeypatch):
    from leak import audit as audit_module

    monkeypatch.setattr(
        audit_module,
        "load_kept_fields",
        lambda dataset_name=None, landmark_tag=None: {
            dataset_name: {"n_patients": 3, "fields": ["b", "a", "b", "c"], "coverage": {}}
        },
    )
    assert load_kept_fields_list("TCGA-SYNTH") == ["b", "a", "c"]


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
    kept_g1 = out_root / "TCGA-KIRC" / "G1_0123456789.json"
    kept_g1.write_text("{}", encoding="utf-8")
    (out_root / "leak_audit_summary.csv").write_text("dataset,scheme\n", encoding="utf-8")

    removed = prune_stale_outputs(out_root, [("TCGA-KIRC", "HGCN_KIRC")])

    assert sorted(removed) == ["CPTAC/", "CPTAC/SURVPGC.json", "TCGA-KIRC/HGCN_LUSC.json"]
    assert (out_root / "TCGA-KIRC" / "HGCN_KIRC.json").exists()
    assert kept_g1.exists()                                       # G1_* 不在 prune 范围
    assert not (out_root / "TCGA-KIRC" / "HGCN_LUSC.json").exists()
    assert not (out_root / "CPTAC").exists()
    assert (out_root / "leak_audit_summary.csv").exists()


# --------------------------------------------------------------------------- 汇总表 & CLI
def test_summary_csv_joins_event_counts(tmp_path):
    payloads, _ = audit_dataset(
        "TCGA-SYNTH",
        [_case("P1", stage="Stage I"), _case("P2", stage="Stage IV",
                                            days_to_diagnosis=100, follow_up_days=300)],
        ["FAKE"],
        {"FAKE": [AGE_FIELD, STAGE_FIELD]},
        kept_field_list=None,
    )
    events = {"TCGA-SYNTH": {"n_event": "42", "event_rate": "0.2500"}}
    rows = summary_rows(payloads, events)

    assert len(rows) == 1
    row = rows[0]
    assert row["dataset"] == "TCGA-SYNTH"
    assert row["scheme"] == "FAKE"
    assert row["n_fields"] == 2
    assert row["n_leaky"] == 1                 # 只有 stage 泄露
    assert row["leaky_ratio"] == "0.500000"
    assert row["n_event"] == "42"
    assert row["event_rate"] == "0.2500"
    assert row["n_leak_total"] == 1
    assert row["n_valid_total"] == 4

    out = write_summary_csv(tmp_path / "nested" / "leak_audit_summary.csv", rows)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == ",".join(SUMMARY_COLUMNS)
    assert "TCGA-SYNTH,FAKE,2,1,0.500000" in lines[1]


def test_payload_records_the_binding():
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


def _write_synthetic_config(tmp_path, *, fields_by_scheme, kept_fields=None):
    clinic_path = tmp_path / "synthetic_cases.json"
    clinic_path.write_text(
        json.dumps(
            [
                _case("P1", stage="Stage I", days_to_diagnosis=0),
                _case("P2", stage="Stage IV", days_to_diagnosis=100, follow_up_days=300),
            ]
        ),
        encoding="utf-8",
    )
    registry = ["TCGA-SYNTH"]
    datasets_path = tmp_path / "datasets.json"
    datasets_path.write_text(
        json.dumps(
            {
                name: {"clinic_files": [str(clinic_path)], "project_ids": []}
                for name in registry
            }
        ),
        encoding="utf-8",
    )
    templates_root = tmp_path / "templates"
    for scheme, fields in fields_by_scheme.items():
        (templates_root / scheme).mkdir(parents=True, exist_ok=True)
        (templates_root / scheme / "fields.json").write_text(
            json.dumps({"fields": fields}), encoding="utf-8"
        )
    return datasets_path, templates_root


def test_cli_writes_scheme_json_g1_json_and_summary(tmp_path, monkeypatch):
    datasets_path, templates_root = _write_synthetic_config(
        tmp_path, fields_by_scheme={"FAKE": [STAGE_FIELD, "project.project_id"]}
    )
    event_summary = tmp_path / "event_summary.csv"
    event_summary.write_text(
        "dataset,n_patients,n_event,n_censored,n_unknown,event_rate\n"
        "TCGA-SYNTH,2,1,1,0,0.5000\n",
        encoding="utf-8",
    )

    from leak import audit as audit_module
    from leak.cli import main

    monkeypatch.setattr(
        audit_module, "load_kept_fields_list", lambda name: [STAGE_FIELD]
    )

    out_dir = tmp_path / "leak_audit"
    code = main(
        [
            "--datasets_config", str(datasets_path),
            "--dataset", "all",
            "--schemes", "FAKE",
            "--templates_root", str(templates_root),
            "--out_dir", str(out_dir),
            "--event_summary", str(event_summary),
            "--quiet",
        ]
    )
    assert code == 0

    payload = json.loads((out_dir / "TCGA-SYNTH" / "FAKE.json").read_text(encoding="utf-8"))
    rows = {row["field"]: row for row in payload["fields"]}
    assert payload["kept_fields_available"] is True
    assert payload["n_patients"] == 2
    assert rows[STAGE_FIELD]["leak_rate"] == 0.5
    assert rows[STAGE_FIELD]["not_in_bank"] is False
    assert rows["project.project_id"]["not_in_bank"] is True
    assert rows["project.project_id"]["leak_rate"] == 0.0

    g1_files = sorted(item.name for item in (out_dir / "TCGA-SYNTH").glob("G1_*.json"))
    assert g1_files == [f"{g1_scheme_name(0)}.json"]
    g1 = json.loads((out_dir / "TCGA-SYNTH" / f"{g1_scheme_name(0)}.json").read_text(encoding="utf-8"))
    assert g1["field"] == STAGE_FIELD and g1["field_idx"] == 0 and g1["leak_rate"] == 0.5

    csv_lines = (out_dir / "leak_audit_summary.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(csv_lines) == 2
    assert csv_lines[1].startswith("TCGA-SYNTH,FAKE,2,1,")
    assert csv_lines[1].endswith(",1,0.5000")


def test_cli_no_g1_skips_field_level_files(tmp_path, monkeypatch):
    datasets_path, templates_root = _write_synthetic_config(
        tmp_path, fields_by_scheme={"FAKE": [STAGE_FIELD]}
    )
    from leak import audit as audit_module
    from leak.cli import main

    monkeypatch.setattr(audit_module, "load_kept_fields_list", lambda name: [STAGE_FIELD])
    out_dir = tmp_path / "leak_audit"
    assert main(
        [
            "--datasets_config", str(datasets_path),
            "--dataset", "all",
            "--schemes", "FAKE",
            "--templates_root", str(templates_root),
            "--out_dir", str(out_dir),
            "--no_g1",
            "--quiet",
        ]
    ) == 0
    assert not list((out_dir / "TCGA-SYNTH").glob("G1_*.json"))
    assert (out_dir / "TCGA-SYNTH" / "FAKE.json").exists()


def test_outputs_are_byte_identical_on_rerun(tmp_path, monkeypatch):
    """同一命令重跑 → 逐字节一致（产物不含时间戳）。"""
    datasets_path, templates_root = _write_synthetic_config(
        tmp_path, fields_by_scheme={"FAKE": [STAGE_FIELD, AGE_FIELD]}
    )
    from leak import audit as audit_module
    from leak.cli import main

    monkeypatch.setattr(
        audit_module, "load_kept_fields_list", lambda name: [STAGE_FIELD, AGE_FIELD]
    )
    argv = [
        "--datasets_config", str(datasets_path),
        "--dataset", "all",
        "--schemes", "FAKE",
        "--templates_root", str(templates_root),
        "--quiet",
    ]
    first, second = tmp_path / "run1", tmp_path / "run2"
    assert main(argv + ["--out_dir", str(first)]) == 0
    assert main(argv + ["--out_dir", str(second)]) == 0

    files_a = sorted(item.relative_to(first) for item in first.rglob("*") if item.is_file())
    files_b = sorted(item.relative_to(second) for item in second.rglob("*") if item.is_file())
    assert files_a == files_b and files_a
    for rel in files_a:
        assert (first / rel).read_bytes() == (second / rel).read_bytes(), rel


def test_template_datasets_key_does_not_drive_the_binding(tmp_path, monkeypatch):
    """绑定只在 src/leak 声明；templates/fields.json 的 datasets 键（旧全绑定）必须被忽略。"""
    clinic_path = tmp_path / "synthetic_cases.json"
    clinic_path.write_text(
        json.dumps([_case("P1", stage="Stage I"), _case("P2", stage="Stage IV")]),
        encoding="utf-8",
    )
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
                "fields": [STAGE_FIELD],
                # 旧字段表把方案全绑定到所有队列——必须不影响范围
                "datasets": ["TCGA-LUSC", "TCGA-KIRC", "CPTAC", "MMRF"],
            }
        ),
        encoding="utf-8",
    )
    (templates_root / "MULTISURV").mkdir(parents=True)
    (templates_root / "MULTISURV" / "fields.json").write_text(
        json.dumps({"fields": [AGE_FIELD], "datasets": []}),
        encoding="utf-8",
    )

    from leak import audit as audit_module
    from leak.cli import main

    monkeypatch.setattr(audit_module, "load_kept_fields_list", lambda name: None)

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
    assert len(summary) == 4
    assert all("CPTAC" not in line and "MMRF" not in line for line in summary[1:])
