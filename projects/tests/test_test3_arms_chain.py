"""Test_3 两臂链路测试：bank 模板方案生成 / greedy 字段读取 / 两臂 Δc 与遗漏字段。

覆盖 scripts/Test_3_custom_scheme.py 与 scripts/Test_3_compare.py；
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import Test_3_common as C  # noqa: E402
import Test_3_compare as CMP  # noqa: E402
import Test_3_custom_scheme as CS  # noqa: E402
from common.fields import field_output_col  # noqa: E402


def test_build_scheme_bank_only_keeps_bank_fields(tmp_path, monkeypatch):
    """bank-only 口径:字段 = 原字段集 ∩ bank;bank 外的进 missing_fields;无 template.csv。"""
    monkeypatch.setattr(CS, "A_TEMPLATES", tmp_path / "templates")
    fields = ["demographic.age_at_index", "diagnoses[].ajcc_pathologic_stage"]
    bank_fields = ["demographic.age_at_index", "demographic.race"]

    out, kept = CS.build_scheme("Test_3_MULTISURV_TCGA-XX", "TCGA-XX", fields, bank_fields,
                                "unit-test", register=False)

    assert kept == ["demographic.age_at_index"]
    payload = json.loads((out / "fields.json").read_text(encoding="utf-8"))
    assert payload["fields"] == ["demographic.age_at_index"]
    assert payload["datasets"] == ["TCGA-XX"]
    assert not (out / "template.csv").exists()  # 句式模板已退役
    meta = json.loads((out / "Test_3_meta.json").read_text(encoding="utf-8"))
    assert meta["n_fields_original"] == 2 and meta["n_fields"] == 1
    assert meta["missing_fields"] == ["diagnoses[].ajcc_pathologic_stage"]
    assert meta["landmark_tag"] == "landmark_0"


def test_build_scheme_all_fields_missing_raises(tmp_path, monkeypatch):
    """bank 里一个字段都没有 → 报错而非生成空方案。"""
    monkeypatch.setattr(CS, "A_TEMPLATES", tmp_path / "templates")
    with pytest.raises(SystemExit):
        CS.build_scheme("Test_3_X", "TCGA-XX", ["diagnoses[].ajcc_pathologic_stage"],
                        ["demographic.race"], "unit-test", register=False)


def test_register_scheme_idempotent(tmp_path):
    schemes_json = tmp_path / "schemes.json"
    schemes_json.write_text(json.dumps({"_schemes": ["A"]}, ensure_ascii=False) + "\n", encoding="utf-8")
    assert CS.register_scheme("Test_3_X", schemes_json) is True
    assert CS.register_scheme("Test_3_X", schemes_json) is False       # 二次登记不动
    payload = json.loads(schemes_json.read_text(encoding="utf-8"))
    assert payload["_schemes"] == ["A", "Test_3_X"]


def test_bank_templates_landmark0_present_and_unknown_dataset_raises():
    tpl = CS.load_bank_templates("TCGA-LAML")
    assert tpl and all(sentence.strip() for sentence in tpl.values())
    with pytest.raises(SystemExit):
        CS.load_bank_templates("TCGA-NOPE")


def test_load_greedy_fields_prefers_recommended_subset(tmp_path):
    result = tmp_path / "result.json"
    result.write_text(json.dumps({"algorithm": "A2_greedy", "recommended_subset": ["f1", "f2"],
                                  "best_subset": ["f1", "f2", "f3"]}), encoding="utf-8")
    fields, algo = CS.load_greedy_fields(result)
    assert fields == ["f1", "f2"] and algo == "A2_greedy"   # 早停点（推荐子集）优先于历史最优
    with pytest.raises(SystemExit):
        CS.load_greedy_fields(tmp_path / "missing.json")


def _write_table(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_fields(path: Path, fields: list[str]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "fields.json").write_text(json.dumps({"fields": fields}), encoding="utf-8")


def _arm_table_rows(dataset: str, values: dict[str, dict[str, float]]) -> list[dict]:
    rows = []
    for scheme, per_modality in values.items():
        for modality, (mean, std) in per_modality.items():
            # F×T 口径:表行 scheme = 臂方案名(work_lm0_* / greedy_lm0_*),不再叠 __landmark_0 后缀
            rows.append({"dataset": dataset, "scheme": scheme, "modality": modality,
                         "val_c_index_mean": mean, "val_c_index_std": std})
    return rows


def _redirect_arm_sources(tmp_path, monkeypatch, *, work_fields, greedy_fields):
    """字段名单来源重定向到 tmp_path(训练时索引口径:work → 论文模板,greedy → result.json)。"""
    import manual_pipeline.arm_names as AN  # noqa: E402

    def _tpl(work: str) -> Path:
        p = tmp_path / "templates" / work / "fields.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"fields": work_fields[work]}), encoding="utf-8")
        return p

    def _greedy(dataset: str) -> Path:
        p = tmp_path / "search" / dataset / "result.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"recommended_subset": greedy_fields[dataset]}), encoding="utf-8")
        return p

    monkeypatch.setattr(AN, "template_json", _tpl)
    monkeypatch.setattr(AN, "greedy_result_json", _greedy)


def test_compare_math_and_missed_fields(tmp_path, monkeypatch):
    dataset, work = "TCGA-XX", "MULTISURV"
    name_b, name_c = C.b_scheme_name(work, dataset), C.c_scheme_name(dataset)
    monkeypatch.setattr(CMP, "ARM_B_RESULTS", tmp_path / "results" / "arm_B")
    _redirect_arm_sources(tmp_path, monkeypatch,
                          work_fields={work: ["a", "b"]}, greedy_fields={dataset: ["a", "c"]})
    _write_table(CMP.ARM_B_RESULTS / f"{dataset}[gdc]" / "cindex.csv",
                 _arm_table_rows(dataset, {
                     name_b: {"mlp_clinic_flatten": (0.60, 0.01), "clinic_cox": (0.57, 0.02)},
                     name_c: {"mlp_clinic_flatten": (0.65, 0.01), "clinic_cox": (0.58, 0.02)},
                 }))

    report = CMP.compare(dataset, work)

    head = report["per_modality"]["mlp_clinic_flatten"]
    assert head["B"]["c"] == 0.60 and head["C"]["c"] == 0.65
    assert head["delta_C_minus_B"] == pytest.approx(0.05)
    assert report["missed_fields"] == ["c"]                 # C \ B
    assert report["n_missed"] == 1 and report["n_fields_greedy"] == 2


def test_compare_raises_when_arm_missing(tmp_path, monkeypatch):
    dataset, work = "TCGA-XX", "MULTISURV"
    monkeypatch.setattr(CMP, "ARM_B_RESULTS", tmp_path / "results" / "arm_B")
    _redirect_arm_sources(tmp_path, monkeypatch,
                          work_fields={work: ["a"]}, greedy_fields={dataset: ["a"]})
    _write_table(CMP.ARM_B_RESULTS / f"{dataset}[gdc]" / "cindex.csv",
                 _arm_table_rows(dataset, {
                     C.b_scheme_name(work, dataset): {"mlp_clinic_flatten": (0.60, 0.01)},
                 }))
    with pytest.raises(CMP.MissingArm):
        CMP.compare(dataset, work)


def test_batch_writes_table_missed_and_figure(tmp_path, monkeypatch):
    dataset, work = "TCGA-XX", "MULTISURV"
    monkeypatch.setattr(CMP, "ARM_B_RESULTS", tmp_path / "results" / "arm_B")
    monkeypatch.setattr(CMP, "OUT_ROOT", tmp_path / "out")
    monkeypatch.setattr(CMP, "DISPLAY_ROOT", tmp_path / "display")
    monkeypatch.setattr(C, "PAN_CANCER_WORKS", (work,))
    monkeypatch.setattr(C, "HGCN_BINDING", {})
    monkeypatch.setattr(C, "main_datasets", lambda *a, **k: [dataset])
    _redirect_arm_sources(tmp_path, monkeypatch,
                          work_fields={work: ["a", "b"]}, greedy_fields={dataset: ["a", "c"]})
    _write_table(CMP.ARM_B_RESULTS / f"{dataset}[gdc]" / "cindex.csv",
                 _arm_table_rows(dataset, {
                     C.b_scheme_name(work, dataset): {"mlp_clinic_flatten": (0.60, 0.01)},
                     C.c_scheme_name(dataset): {"mlp_clinic_flatten": (0.66, 0.01)},
                 }))

    result = CMP.batch([dataset])

    assert result["done"] == 1 and result["pending"] == []
    table = pd.read_csv(result["table"])
    assert table.iloc[0]["delta_C_minus_B"] == pytest.approx(0.06)
    missed = pd.read_csv(result["missed"])
    assert missed["field"].tolist() == ["c"]
    # 展示层镜像 + Δc 图（spec §7.3）；matplotlib 缺失时 figure 为 None 不算失败
    assert (CMP.DISPLAY_ROOT / "two_arm.csv").exists()
    if result["figure"] is not None:
        assert Path(result["figure"]).exists()

