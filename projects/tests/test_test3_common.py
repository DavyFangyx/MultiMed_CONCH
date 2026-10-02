"""Test_3 共享口径测试：主集读取（不硬编码）/ 方案绑定 / 路径与命名。

口径：z_notes/Test_series_spec.md §2.4（绑定）、§7（Test_3 产物）、§12 R13（主集 n_event>=100）。
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src", ROOT / "scripts", ROOT / "A_pipeline"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import Test_3_common as C  # noqa: E402


def _manifest_recompute(threshold: int = 100) -> list[str]:
    """独立地从 manifest.csv 重算主集（与 C.main_datasets 的实现路径不同）。"""
    with C.MANIFEST_CSV.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return sorted(row["dataset"].strip() for row in rows
                  if row["dataset"].strip().upper().startswith("TCGA")
                  and int(float(row["n_event"])) >= threshold)


def test_main_datasets_matches_manifest_recomputed():
    main = C.main_datasets()
    assert main == _manifest_recompute()
    # R13 主集数 15：数字本身也来自数据核对（任一来源增删数据集即失败）
    assert len(main) == 15
    assert main == sorted(main)  # 字典序，产物路径可预期


def test_main_datasets_threshold_is_data_driven():
    synth = {"TCGA-X": 100, "TCGA-Y": 99, "TCGA-Z": 101, "CPTAC-PDA": 500}
    assert C.main_datasets(synth) == ["TCGA-X", "TCGA-Z"]
    assert C.main_datasets(synth, threshold=99) == ["TCGA-X", "TCGA-Y", "TCGA-Z"]


def test_load_n_event_crosscheck_raises_on_mismatch(tmp_path):
    manifest = tmp_path / "manifest.csv"
    summary = tmp_path / "event_summary.csv"
    manifest.write_text("dataset,n_event\nTCGA-X,100\n", encoding="utf-8")
    summary.write_text("dataset,n_event\nTCGA-X,101\n", encoding="utf-8")
    try:
        C.load_n_event(manifest, summary, strict=True)
    except ValueError as exc:
        assert "TCGA-X" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("两来源不一致应报错")


def test_load_n_event_skips_non_tcga_and_prefers_manifest(tmp_path):
    manifest = tmp_path / "manifest.csv"
    summary = tmp_path / "event_summary.csv"
    manifest.write_text("dataset,n_event\nTCGA-X,100\nCPTAC-PDA,888\n", encoding="utf-8")
    summary.write_text("dataset,n_event\nTCGA-X,100\nTCGA-Y,250\nMMRF,999\n", encoding="utf-8")
    table = C.load_n_event(manifest, summary)
    assert "CPTAC-PDA" not in table and "MMRF" not in table
    assert table == {"TCGA-X": 100, "TCGA-Y": 250}


def test_work_pairs_binding_rule():
    datasets = C.main_datasets()
    pairs = C.work_pairs(datasets)
    n_bound = sum(1 for d in datasets if d in C.HGCN_BINDING)
    assert len(pairs) == len(datasets) * 4 + n_bound  # 泛癌种 4 方案 + HGCN 绑定（主集内 4 个癌种）
    for dataset in datasets:
        for work in C.PAN_CANCER_WORKS:
            assert (dataset, work) in pairs
    # §2.4：HGCN_* 只允许出现在自己的癌种
    for dataset, work in pairs:
        if work.startswith("HGCN_"):
            assert C.HGCN_BINDING.get(dataset) == work
    assert ("TCGA_LIHC", "HGCN_LIHC") in pairs
    assert ("TCGA-BRCA", "HGCN_BRCA") not in pairs
    # 绑定表覆盖 6 个 HGCN 方案；其中落在 R13 主集内的是 4 个（ESCA/UCEC 事件数不足，不参与训练类主集）
    assert len(C.HGCN_BINDING) == 6
    assert {d for d in C.HGCN_BINDING if d in datasets} == {"TCGA-KIRC", "TCGA_LIHC", "TCGA-LUSC", "TCGA-LUAD"}


def test_paths_and_scheme_names():
    assert C.search_seed_dir("TCGA-LAML").as_posix().endswith(
        "results/Test_3_greedy_vs_works/search/TCGA-LAML/mlp_clinic_flatten/seed_0")
    assert C.search_result_json("TCGA-LAML").name == "result.json"
    assert C.search_evaluations_jsonl("TCGA-LAML").name == "evaluations.jsonl"
    assert C.bp_scheme_name("MULTISURV", "TCGA_LIHC") == "Test_3_MULTISURV_TCGA_LIHC"
    assert C.c_scheme_name("TCGA-LAML") == "Test_3_greedy_TCGA-LAML"
    assert C.c_scheme_name("TCGA-LAML", kind="best") == "Test_3_greedybest_TCGA-LAML"
    assert C.ANALYZER == "mlp_clinic_flatten" and C.ALGO == "A2_greedy" and C.SEED == 0
    assert C.LANDMARK_TIME == "0"
