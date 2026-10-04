"""S6 续跑: Test_4_three_tiers.py（三档汇总表：报告值/去泄露值/可达值）回归测试。

覆盖：
  1. tier_for —— 协议 A 四档边界（100 / 70 / 30）；
  2. 三档装配与档间 Δ —— 值逐位、Δ=手算差（6 位舍入）、cox 交叉列；
  3. 缺可达值不中断 —— 整行保留、C 列记 "pending"、Δ2 同为 pending（与 Test_3_compare 同哲学）；
  4. 全缺不崩溃 —— three_arm 空表 / 文件缺失 -> 全行 pending，写出与聚合正常；
  5. 写出 —— Main_three_tiers.csv / Main_tier_summary.csv 列名、行数、tier 聚合计数；
  6. 对齐 three_arm —— delta_C_minus_Bp / n_fields_greedy / n_missed 引用一致。

运行：
  python3 -m pytest tests/test_test4_three_tiers.py -q
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "results_display" / "scripts" / "Test_4_three_tiers.py"


def _load_by_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


t4 = _load_by_path("s6_test4_three_tiers", SCRIPT)

ARM_COLS = ["dataset", "scheme", "encoding", "modality", "clinic_dir", "results_dir",
            "log_path", "skipped", "val_c_index_mean", "val_c_index_std",
            "test_c_index_mean", "test_c_index_std", "source"]
THREE_ARM_COLS = ["dataset", "work", "n_fields_work", "n_fields_greedy",
                  "B_c", "B_std", "Bp_c", "Bp_std", "C_c", "C_std",
                  "delta_C_minus_Bp", "delta_C_minus_B", "n_missed",
                  "B_cox_c", "delta_C_minus_B_cox"]

DATASETS = ["TCGA-AAA", "TCGA-BBB"]
PAIRS = [("TCGA-AAA", "W1"), ("TCGA-AAA", "W2"),
         ("TCGA-BBB", "W1"), ("TCGA-BBB", "W2")]
N_EVENT = {"TCGA-AAA": 120, "TCGA-BBB": 80}


def _write_cindex(root: Path, dataset: str, rows: list[dict]) -> None:
    out = Path(root) / f"{dataset}[gdc]"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "cindex.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=ARM_COLS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in ARM_COLS})


def _arm_row(dataset: str, scheme: str, modality: str, mean: float, std: float) -> dict:
    return {
        "dataset": f"{dataset}[gdc]", "scheme": scheme, "encoding": "prompt",
        "modality": modality, "results_dir": f"/nonexistent/{dataset}/{scheme}/{modality}",
        "skipped": True, "val_c_index_mean": mean, "val_c_index_std": std,
        "test_c_index_mean": mean, "test_c_index_std": std, "source": "val",
    }


def _write_three_arm(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=THREE_ARM_COLS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in THREE_ARM_COLS})


def _templates(tmp_path: Path) -> Path:
    """W1 五字段 / W2 三字段（工作组合字段数）。"""
    templates = tmp_path / "templates"
    for work, n in (("W1", 5), ("W2", 3)):
        (templates / work).mkdir(parents=True, exist_ok=True)
        (templates / work / "fields.json").write_text(
            json.dumps({"fields": [f"f{i}" for i in range(n)]}), encoding="utf-8")
    return templates


def _fixture(tmp_path: Path):
    """三档源表：ds1 报告/去泄露/可达齐；ds2 缺可达；W2 仅 ds1 有报告值。"""
    arm_a, arm_b = tmp_path / "arm_a", tmp_path / "arm_b"
    _write_cindex(arm_a, "TCGA-AAA", [
        _arm_row("TCGA-AAA", "W1", "mlp_clinic_flatten", 0.700, 0.050),
        _arm_row("TCGA-AAA", "W1", "clinic_cox", 0.600, 0.040),
    ])
    _write_cindex(arm_a, "TCGA-BBB", [
        _arm_row("TCGA-BBB", "W1", "mlp_clinic_flatten", 0.620, 0.030),
        _arm_row("TCGA-BBB", "W1", "clinic_cox", 0.530, 0.020),
    ])
    _write_cindex(arm_b, "TCGA-AAA", [
        _arm_row("TCGA-AAA", "W1__landmark_0", "mlp_clinic_flatten", 0.650, 0.055),
        _arm_row("TCGA-AAA", "W1__landmark_0", "clinic_cox", 0.580, 0.045),
        _arm_row("TCGA-AAA", "W2__landmark_0", "mlp_clinic_flatten", 0.640, 0.050),
        _arm_row("TCGA-AAA", "W2__landmark_0", "clinic_cox", 0.550, 0.044),
    ])
    _write_cindex(arm_b, "TCGA-BBB", [
        _arm_row("TCGA-BBB", "W1__landmark_0", "mlp_clinic_flatten", 0.600, 0.035),
        _arm_row("TCGA-BBB", "W1__landmark_0", "clinic_cox", 0.500, 0.025),
        _arm_row("TCGA-BBB", "W2__landmark_0", "mlp_clinic_flatten", 0.610, 0.036),
        _arm_row("TCGA-BBB", "W2__landmark_0", "clinic_cox", 0.510, 0.026),
    ])
    three_arm = tmp_path / "three_arm.csv"
    _write_three_arm(three_arm, [
        {"dataset": "TCGA-AAA", "work": "W1", "n_fields_work": 5, "n_fields_greedy": 3,
         "B_c": 0.650, "B_std": 0.055, "Bp_c": 0.645, "Bp_std": 0.054,
         "C_c": 0.600, "C_std": 0.060, "delta_C_minus_Bp": -0.045,
         "delta_C_minus_B": -0.050, "n_missed": 2, "B_cox_c": 0.580, "delta_C_minus_B_cox": ""},
        {"dataset": "TCGA-AAA", "work": "W2", "n_fields_work": 3, "n_fields_greedy": 2,
         "B_c": 0.640, "B_std": 0.050, "Bp_c": 0.630, "Bp_std": 0.051,
         "C_c": 0.590, "C_std": 0.061, "delta_C_minus_Bp": -0.040,
         "delta_C_minus_B": -0.050, "n_missed": 1, "B_cox_c": 0.550, "delta_C_minus_B_cox": ""},
    ])
    return dict(arm_a=arm_a, arm_b=arm_b, three_arm=three_arm, templates=_templates(tmp_path))


def _build(tmp_path: Path):
    fx = _fixture(tmp_path)
    rows = t4.build_rows(DATASETS, PAIRS, N_EVENT,
                         arm_a_root=fx["arm_a"], arm_b_root=fx["arm_b"],
                         three_arm=t4.load_three_arm(fx["three_arm"]),
                         templates=fx["templates"])
    return rows, fx


def _row(rows, dataset, work):
    return next(r for r in rows if r["dataset"] == dataset and r["work"] == work)


# ------------------------------------------------------------------ 1. 分层
def test_tier_for_boundaries():
    assert t4.tier_for(100) == "main"
    assert t4.tier_for(1000) == "main"
    assert t4.tier_for(99) == "main_ci"
    assert t4.tier_for(70) == "main_ci"
    assert t4.tier_for(69) == "supp"
    assert t4.tier_for(30) == "supp"
    assert t4.tier_for(29) == "low"
    assert t4.tier_for(0) == "low"


# ------------------------------------------------------------------ 2. 装配与 Δ
def test_build_rows_three_tiers_and_deltas(tmp_path):
    rows, _ = _build(tmp_path)
    assert len(rows) == 4  # 缺臂不丢行
    r = _row(rows, "TCGA-AAA", "W1")
    assert r["status"] == "ok"
    assert r["tier"] == "main" and r["n_event"] == 120
    assert r["n_fields_work"] == 5
    assert r["report_c"] == 0.700 and r["report_std"] == 0.050
    assert r["deleak_c"] == 0.650 and r["deleak_std"] == 0.055
    assert r["delta_report_minus_deleak"] == round(0.700 - 0.650, 6)
    assert r["reach_c"] == 0.600 and r["reach_std"] == 0.060
    assert r["reach_bp_c"] == 0.645
    assert r["delta_deleak_minus_reach"] == round(0.650 - 0.600, 6)
    assert r["delta_C_minus_Bp"] == -0.045
    assert r["n_fields_greedy"] == 3 and r["n_missed"] == 2
    assert r["report_cox_c"] == 0.600 and r["deleak_cox_c"] == 0.580
    assert r["delta_report_minus_deleak_cox"] == round(0.600 - 0.580, 6)
    # 报告值缺（W2 未在 arm_A 报告）-> n/a，但可达值仍在
    r2 = _row(rows, "TCGA-AAA", "W2")
    assert r2["report_c"] == t4.NA and r2["delta_report_minus_deleak"] == t4.NA
    assert r2["status"] == "ok" and r2["reach_c"] == 0.590
    # tier 排序：main 在前（main_ci 行排后）
    assert [r["tier"] for r in rows] == ["main", "main", "main_ci", "main_ci"]


# ------------------------------------------------------- 3. 缺可达值不中断
def test_missing_C_keeps_row_pending(tmp_path):
    rows, _ = _build(tmp_path)
    r = _row(rows, "TCGA-BBB", "W1")  # three_arm 无该行
    assert r["status"] == "pending_C"
    assert r["reach_c"] == t4.PENDING and r["reach_std"] == t4.PENDING
    assert r["reach_bp_c"] == t4.PENDING and r["reach_bp_std"] == t4.PENDING
    assert r["delta_deleak_minus_reach"] == t4.PENDING
    assert r["delta_C_minus_Bp"] == t4.PENDING
    assert r["n_fields_greedy"] == t4.PENDING and r["n_missed"] == t4.PENDING
    # 其余档（报告/去泄露/Δ1）照常保留
    assert r["report_c"] == 0.620 and r["deleak_c"] == 0.600
    assert r["delta_report_minus_deleak"] == round(0.620 - 0.600, 6)
    assert r["tier"] == "main_ci" and r["n_fields_work"] == 5


# ------------------------------------------------------- 4. 全缺不崩溃
@pytest.mark.parametrize("mode", ["header_only", "file_missing"])
def test_all_missing_C_does_not_crash(tmp_path, mode):
    rows, fx = _build(tmp_path)
    if mode == "header_only":
        _write_three_arm(fx["three_arm"], [])  # 只剩表头
        arm3 = t4.load_three_arm(fx["three_arm"])
    else:
        arm3 = t4.load_three_arm(tmp_path / "missing.csv")  # 文件缺失
    rows = t4.build_rows(DATASETS, PAIRS, N_EVENT,
                         arm_a_root=fx["arm_a"], arm_b_root=fx["arm_b"],
                         three_arm=arm3, templates=fx["templates"])
    assert len(rows) == len(PAIRS)
    assert all(r["status"] == "pending_C" for r in rows)
    assert all(r["reach_c"] == t4.PENDING for r in rows)
    written = t4.write_tables(rows, tmp_path / "out")
    assert all(p.exists() for p in written)
    summary = list(csv.DictReader((tmp_path / "out" / "Main_tier_summary.csv").open()))
    assert {(s["tier"], s["n_ok"]) for s in summary} == {("main", "0"), ("main_ci", "0")}
    assert all(s["delta2_mean"] == "" and s["delta2_median"] == "" for s in summary)


# ------------------------------------------------------- 5. 写出与聚合
def test_write_tables_outputs(tmp_path):
    rows, _ = _build(tmp_path)
    out = tmp_path / "out"
    written = t4.write_tables(rows, out)
    assert [p.name for p in written] == ["Main_three_tiers.csv", "Main_tier_summary.csv"]
    with (out / "Main_three_tiers.csv").open() as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == t4.FIELDS
        body = list(reader)
    assert len(body) == 4
    text = (out / "Main_three_tiers.csv").read_text(encoding="utf-8")
    assert t4.PENDING in text and t4.NA in text  # 缺项以字面量落盘
    summary = list(csv.DictReader((out / "Main_tier_summary.csv").open()))
    assert len(summary) == 2
    main = next(s for s in summary if s["tier"] == "main")
    assert main["n_pairs"] == "2" and main["n_ok"] == "2" and main["n_pending_C"] == "0"
    assert main["n_report_unavailable"] == "1"  # W2 无报告值（Δ1 只在有报告的 1 行上平均）
    assert main["delta1_mean"] == str(round(0.700 - 0.650, 6))
    assert main["delta1_median"] == str(round(0.700 - 0.650, 6))
    assert main["delta2_mean"] == str(round(((0.650 - 0.600) + (0.640 - 0.590)) / 2, 6))
    main_ci = next(s for s in summary if s["tier"] == "main_ci")
    assert main_ci["n_pairs"] == "2" and main_ci["n_ok"] == "0" and main_ci["n_pending_C"] == "2"


# ------------------------------------------------------- 6. 与 three_arm 对齐
def test_three_arm_alignment(tmp_path):
    rows, fx = _build(tmp_path)
    arm3 = t4.load_three_arm(fx["three_arm"])
    for r in rows:
        src = arm3.get((r["dataset"], r["work"]))
        if src is None:
            assert r["status"] == "pending_C"
            continue
        assert r["delta_C_minus_Bp"] == float(src["delta_C_minus_Bp"])
        assert r["reach_c"] == float(src["C_c"]) and r["reach_bp_c"] == float(src["Bp_c"])
        assert r["n_fields_greedy"] == int(src["n_fields_greedy"])
        assert r["n_missed"] == int(src["n_missed"])
        assert r["n_fields_work"] == int(src["n_fields_work"])  # 表口径自洽
    # 缺 n_event -> 显式报错（不静默）
    with pytest.raises(SystemExit):
        t4.build_rows(["TCGA-XXX"], [("TCGA-XXX", "W1")], N_EVENT,
                      arm_a_root=fx["arm_a"], arm_b_root=fx["arm_b"],
                      three_arm={}, templates=fx["templates"])
