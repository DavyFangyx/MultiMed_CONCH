"""Test_3 共享口径测试：主集读取（不硬编码）/ 方案绑定 / 路径与命名。

口径：z_notes/Test_series_spec.md §2.4（绑定）、§7（Test_3 产物）、§12 R13
（主集 = label 宇宙有效事件 >= 100，2026-10-09 口径，13 主集）。
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import Test_3_common as C  # noqa: E402

MAIN_13 = [
    "TCGA-BLCA", "TCGA-BRCA", "TCGA-GBM", "TCGA-HNSC", "TCGA-LAML", "TCGA-LGG",
    "TCGA-LUAD", "TCGA-LUSC", "TCGA-OV", "TCGA-PAAD", "TCGA-SKCM", "TCGA-STAD",
    "TCGA_LIHC",
]


def test_main_datasets_is_13_roster():
    main = C.main_datasets()
    # R13 主集 = 13（2026-10-09 口径：label 宇宙有效事件 >= 100；原 15 主集 − COAD 90 − KIRC 86）
    assert main == MAIN_13
    assert main == sorted(main)  # 字典序，产物路径可预期


def test_main_datasets_threshold_is_data_driven():
    synth = {"TCGA-X": 100, "TCGA-Y": 99, "TCGA-Z": 101, "CPTAC-PDA": 500}
    assert C.main_datasets(synth) == ["TCGA-X", "TCGA-Z"]
    assert C.main_datasets(synth, threshold=99) == ["TCGA-X", "TCGA-Y", "TCGA-Z"]


def test_load_n_event_crosscheck_raises_on_mismatch(tmp_path):
    summary = tmp_path / "event_summary.csv"
    # 真实 TCGA-COAD 的 label 宇宙有效事件 = 90；summary 故意写错 → 交叉核对报错
    summary.write_text("dataset,n_event_label\nTCGA-COAD,999\n", encoding="utf-8")
    try:
        C.load_n_event(C.MANIFEST_CSV, summary, strict=True)
    except ValueError as exc:
        assert "TCGA-COAD" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("n_event_label 与 label metadata 不一致应报错")


def test_load_n_event_returns_tcga_label_events(tmp_path):
    from common.patient_universe import label_event_count

    table = C.load_n_event(C.MANIFEST_CSV, tmp_path / "event_summary.csv")
    assert all(name.upper().startswith("TCGA") for name in table)
    assert "TCGA_LIHC" in table and "TCGA-LIHC" not in table  # 下划线变体优先
    assert "CPTAC" not in table and "MMRF" not in table
    assert table["TCGA-COAD"] == label_event_count("TCGA-COAD")["n_event"] == 90
    assert table["TCGA-KIRC"] == label_event_count("TCGA-KIRC")["n_event"] == 86


def test_work_pairs_binding_rule():
    datasets = C.main_datasets()
    pairs = C.work_pairs(datasets)
    n_bound = sum(1 for d in datasets if d in C.HGCN_BINDING)
    assert len(pairs) == len(datasets) * 4 + n_bound  # 泛癌种 4 方案 + HGCN 绑定
    for dataset in datasets:
        for work in C.PAN_CANCER_WORKS:
            assert (dataset, work) in pairs
    # §2.4：HGCN_* 只允许出现在自己的癌种
    for dataset, work in pairs:
        if work.startswith("HGCN_"):
            assert C.HGCN_BINDING.get(dataset) == work
    assert ("TCGA_LIHC", "HGCN_LIHC") in pairs
    assert ("TCGA-BRCA", "HGCN_BRCA") not in pairs
    # 绑定表覆盖 6 个 HGCN 方案；落在 13 主集内的是 3 个（KIRC/ESCA/UCEC 事件数不足）
    assert len(C.HGCN_BINDING) == 6
    assert {d for d in C.HGCN_BINDING if d in datasets} == {"TCGA_LIHC", "TCGA-LUSC", "TCGA-LUAD"}


def test_paths_and_scheme_names():
    assert C.search_seed_dir("TCGA-LAML").as_posix().endswith(
        "results/Test_3_greedy_vs_works/search/TCGA-LAML/mlp_clinic_flatten/seed_0")
    assert C.search_result_json("TCGA-LAML").name == "result.json"
    assert C.search_evaluations_jsonl("TCGA-LAML").name == "evaluations.jsonl"
    assert C.b_scheme_name("MULTISURV", "TCGA_LIHC") == "Test_3_MULTISURV_TCGA_LIHC"
    assert C.c_scheme_name("TCGA-LAML") == "Test_3_greedy_TCGA-LAML"
    assert C.c_scheme_name("TCGA-LAML", kind="best") == "Test_3_greedybest_TCGA-LAML"
    assert C.ANALYZER == "mlp_clinic_flatten" and C.ALGO == "A2_greedy" and C.SEED == 0
    assert C.LANDMARK_TIME == "0"
