"""Test_3 三臂链路测试：bank 模板方案生成 / greedy 字段读取 / 三臂 Δc 与遗漏字段。

覆盖 scripts/Test_3_custom_scheme.py 与 scripts/Test_3_compare.py；
A_pipeline 进程内补丁（Test_3_pipeline_one）以子进程方式验证，避免测试进程 sys.path 被翻转
（A_pipeline 与 projects 都有 `src` 包，导入顺序敏感）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src", ROOT / "scripts", ROOT / "A_pipeline"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import Test_3_common as C  # noqa: E402
import Test_3_compare as CMP  # noqa: E402
import Test_3_custom_scheme as CS  # noqa: E402
from common.fields import field_output_col  # noqa: E402


def test_build_scheme_writes_fields_template_and_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(CS, "A_TEMPLATES", tmp_path / "templates")
    fields = ["demographic.age_at_index", "diagnoses[].ajcc_pathologic_stage"]
    bank = {"demographic.age_at_index": "The patient is {} years old at index."}
    scheme_tpl = {field_output_col("diagnoses[].ajcc_pathologic_stage"): "Pathologic overall stage is {}."}

    out = CS.build_scheme("Test_3_MULTISURV_TCGA-XX", "TCGA-XX", fields, bank, scheme_tpl,
                          "unit-test", register=False)

    payload = json.loads((out / "fields.json").read_text(encoding="utf-8"))
    assert payload["fields"] == fields and payload["datasets"] == ["TCGA-XX"]
    tpl = pd.read_csv(out / "template.csv")
    assert list(tpl.columns) == [field_output_col(f) for f in fields]
    assert tpl.iloc[0][field_output_col("demographic.age_at_index")] == bank["demographic.age_at_index"]
    assert tpl.iloc[0][field_output_col("diagnoses[].ajcc_pathologic_stage")] == \
        scheme_tpl[field_output_col("diagnoses[].ajcc_pathologic_stage")]
    meta = json.loads((out / "Test_3_meta.json").read_text(encoding="utf-8"))
    assert meta["n_fields"] == 2 and meta["bank_template_fields"] == 1
    assert meta["fallback_fields"] == ["diagnoses[].ajcc_pathologic_stage"]
    assert meta["landmark_tag"] == "landmark_0"


def test_build_scheme_without_any_template_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(CS, "A_TEMPLATES", tmp_path / "templates")
    with pytest.raises(SystemExit):
        CS.build_scheme("Test_3_X", "TCGA-XX", ["demographic.age_at_index"], {}, {}, "unit-test",
                        register=False)


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
            rows.append({"dataset": dataset, "scheme": f"{scheme}__landmark_0", "modality": modality,
                         "val_c_index_mean": mean, "val_c_index_std": std})
    return rows


def test_compare_math_and_missed_fields(tmp_path, monkeypatch):
    dataset, work = "TCGA-XX", "MULTISURV"
    name_bp, name_c = C.bp_scheme_name(work, dataset), C.c_scheme_name(dataset)
    work_fields = ["a", "b"]
    c_fields = ["a", "c"]
    monkeypatch.setattr(CMP, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(CMP, "A_TEMPLATES", tmp_path / "templates")
    _write_table(CMP.RESULTS / "A_manual_landmark" / f"{dataset}[gdc]" / "cindex.csv",
                 _arm_table_rows(dataset, {
                     work: {"mlp_clinic_flatten": (0.50, 0.01), "clinic_cox": (0.55, 0.02)},
                     name_bp: {"mlp_clinic_flatten": (0.60, 0.01), "clinic_cox": (0.57, 0.02)},
                     name_c: {"mlp_clinic_flatten": (0.65, 0.01), "clinic_cox": (0.58, 0.02)},
                 }))
    _write_fields(CMP.A_TEMPLATES / work, work_fields)
    _write_fields(CMP.A_TEMPLATES / name_c, c_fields)

    report = CMP.compare(dataset, work)

    head = report["per_modality"]["mlp_clinic_flatten"]
    assert head["B"]["c"] == 0.50 and head["Bp"]["c"] == 0.60 and head["C"]["c"] == 0.65
    assert head["delta_C_minus_Bp"] == pytest.approx(0.05)
    assert head["delta_C_minus_B"] == pytest.approx(0.15)
    assert report["missed_fields"] == ["c"]                 # C \ work
    assert report["n_missed"] == 1 and report["n_fields_greedy"] == 2


def test_compare_raises_when_arm_missing(tmp_path, monkeypatch):
    dataset, work = "TCGA-XX", "MULTISURV"
    monkeypatch.setattr(CMP, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(CMP, "A_TEMPLATES", tmp_path / "templates")
    _write_table(CMP.RESULTS / "A_manual_landmark" / f"{dataset}[gdc]" / "cindex.csv",
                 _arm_table_rows(dataset, {
                     work: {"mlp_clinic_flatten": (0.50, 0.01)},
                     C.bp_scheme_name(work, dataset): {"mlp_clinic_flatten": (0.60, 0.01)},
                 }))
    _write_fields(CMP.A_TEMPLATES / work, ["a"])
    _write_fields(CMP.A_TEMPLATES / C.c_scheme_name(dataset), ["a"])
    with pytest.raises(CMP.MissingArm):
        CMP.compare(dataset, work)


def test_pipeline_one_patches_are_in_memory_only():
    """子进程验证：方案白名单追加 + DEFAULT_GPU 改写，且 schemes.json 不被改写。"""
    schemes_json = ROOT / "A_pipeline" / "templates" / "schemes.json"
    before = schemes_json.read_bytes()
    code = (
        "import json,sys;"
        f"sys.path.insert(0, {str(ROOT / 'scripts')!r});"
        "import Test_3_pipeline_one as P;"
        "from src import config, paths, encode;"
        "n=len(config.PAPER_SCHEMES);"
        "s=P.apply_patches('1');"
        "assert all(name in config.PAPER_SCHEMES for name in s['added_schemes']);"
        "assert config.PAPER_SCHEMES is config.ALL_TEXT_SCHEMES or n <= len(config.ALL_TEXT_SCHEMES);"
        "assert paths.DEFAULT_GPU=='1' and encode.DEFAULT_GPU=='1';"
        "print(json.dumps({'added':len(s['added_schemes']),'gpu':s['gpu']}))"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-800:]
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    assert summary["added"] > 0 and summary["gpu"] == "1"
    assert schemes_json.read_bytes() == before               # 磁盘文件零改动
