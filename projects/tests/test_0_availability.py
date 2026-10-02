"""Test_0 可用数据集评估脚本的分层规则测试（全部使用假数据，不触碰真实数据）。

规格：z_notes/Test_series_spec.md §4.2 / §4.3。
"""

import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import run_Test_0_availability as test_0
from run_Test_0_availability import (
    MANIFEST_COLUMNS,
    base_tier,
    classify_tier,
    degen_fold_indices,
    epv_field_budget,
    fold_events_from_splits,
    format_per_fold,
    manifest_row,
    parse_per_fold,
    run,
    strict_landmark_events,
    study_name_for,
)


# ---------------------------------------------------------------------------
# R1–R4 基础档位
# ---------------------------------------------------------------------------


def test_base_tier_boundaries():
    # R1 主集：n_event >= 150
    assert base_tier(150) == ("main", "R1")
    assert base_tier(700) == ("main", "R1")
    # R2 扩展集：70 <= n_event < 150
    assert base_tier(149) == ("extended", "R2")
    assert base_tier(70) == ("extended", "R2")
    # R3 补充集：30 <= n_event < 70
    assert base_tier(69) == ("supplementary", "R3")
    assert base_tier(30) == ("supplementary", "R3")
    # R4 排除集：n_event < 30
    assert base_tier(29) == ("excluded", "R4")
    assert base_tier(1) == ("excluded", "R4")
    assert base_tier(0) == ("excluded", "R4")


def test_classify_tier_without_downgrade():
    # event_rate 不触发 R5 时，tier == 基础档位
    for n_event, expected in [
        (150, "main"),
        (200, "main"),
        (149, "extended"),
        (70, "extended"),
        (69, "supplementary"),
        (30, "supplementary"),
        (29, "excluded"),
    ]:
        tier, base, hits = classify_tier(n_event, 0.5)
        assert tier == expected == base
        assert len(hits) == 1 and hits[0].startswith("R")


def test_rate_exactly_at_floor_is_not_downgraded():
    # R5 是严格小于：event_rate == 0.1 不降级
    tier, base, hits = classify_tier(200, 0.1)
    assert (tier, base) == ("main", "main")
    assert "R5" not in hits


# ---------------------------------------------------------------------------
# R5 次级规则：event_rate < 0.1 降一级
# ---------------------------------------------------------------------------


def test_rate_downgrade_one_level():
    # main -> extended
    tier, base, hits = classify_tier(200, 0.05)
    assert (tier, base) == ("extended", "main")
    assert hits == ["R1", "R5"]
    # extended -> supplementary
    tier, base, hits = classify_tier(90, 0.09)
    assert (tier, base) == ("supplementary", "extended")
    assert hits == ["R2", "R5"]
    # supplementary -> excluded
    tier, base, hits = classify_tier(40, 0.05)
    assert (tier, base) == ("excluded", "supplementary")
    assert hits == ["R3", "R5"]


def test_rate_downgrade_does_not_go_below_excluded():
    # excluded 已是最低档，不再下调，但 R5 依然记录
    tier, base, hits = classify_tier(10, 0.02)
    assert (tier, base) == ("excluded", "excluded")
    assert hits == ["R4", "R5"]


def test_rate_missing_skips_rule5():
    for missing in (None, float("nan"), ""):
        tier, base, hits = classify_tier(200, missing)
        assert (tier, base) == ("main", "main")
        assert "R5" not in hits


# ---------------------------------------------------------------------------
# R7 退化折 / R8 EPV
# ---------------------------------------------------------------------------


def test_degen_fold_indices():
    assert degen_fold_indices([30, 29, 1, 0, 2]) == [2, 3]
    assert degen_fold_indices([40, 40, 40, 40, 40]) == []
    assert degen_fold_indices([]) == []
    assert degen_fold_indices(None) == []
    # 恰好 2 个事件不是退化折（c-index 可取连续值）
    assert degen_fold_indices([2]) == []


def test_epv_field_budget():
    assert epv_field_budget([40, 40, 40, 40, 40]) == 4
    assert epv_field_budget([30, 29, 29, 29, 29]) == 2
    assert epv_field_budget([7, 7, 6, 6, 6]) == 0
    assert epv_field_budget([]) == 0


def test_per_fold_format_roundtrip():
    assert format_per_fold([39, 38, 38, 38, 38]) == "39|38|38|38|38"
    assert parse_per_fold("39|38|38|38|38") == [39, 38, 38, 38, 38]
    assert parse_per_fold("") == []
    assert format_per_fold([]) == ""


# ---------------------------------------------------------------------------
# 输入读取：每折事件数 / 每折患者数
# ---------------------------------------------------------------------------


def _fake_event_stats(rows):
    return pd.DataFrame(rows, columns=["submitter_id", "case_id", "event", "ground_truth_time"])


def _write_splits(split_dir: Path, folds):
    """folds: list of (train_ids, val_ids)。"""
    split_dir.mkdir(parents=True, exist_ok=True)
    for i, (train_ids, val_ids) in enumerate(folds):
        width = max(len(train_ids), len(val_ids), 1)
        frame = pd.DataFrame(
            {
                "train": list(train_ids) + [None] * (width - len(train_ids)),
                "val": list(val_ids) + [None] * (width - len(val_ids)),
                "test": list(val_ids) + [None] * (width - len(val_ids)),
            }
        )
        frame.to_csv(split_dir / f"splits_{i}.csv", index=False)


def test_fold_events_from_splits(tmp_path):
    per = _fake_event_stats(
        [
            ("A", "a", 1, 100.0),
            ("B", "b", 0, 200.0),
            ("C", "c", 1, 300.0),
            ("D", "d", 1, 400.0),
        ]
    )
    split_dir = tmp_path / "tcga_aa"
    _write_splits(split_dir, [(["A"], ["B", "C"]), (["B"], ["A", "D"])])

    per_fold_events, per_fold_patients, warnings = fold_events_from_splits(split_dir, per)
    assert per_fold_events == [1, 2]
    assert per_fold_patients == [2, 2]
    assert warnings == []


def test_fold_events_orders_by_numeric_fold_index(tmp_path):
    # 折序按 splits_{i} 的数字升序（不是字典序）
    per = _fake_event_stats([("A", "a", 1, 10.0), ("B", "b", 1, 10.0), ("C", "c", 0, 10.0)])
    split_dir = tmp_path / "tcga_aa"
    split_dir.mkdir(parents=True)
    for i, ids in {0: ["A"], 2: ["B"], 10: ["C"]}.items():
        pd.DataFrame({"train": [None], "val": ids, "test": ids}).to_csv(split_dir / f"splits_{i}.csv", index=False)

    per_fold_events, _, _ = fold_events_from_splits(split_dir, per)
    assert per_fold_events == [1, 1, 0]


def test_fold_events_missing_split_dir(tmp_path):
    per = _fake_event_stats([("A", "a", 1, 10.0)])
    per_fold_events, _, warnings = fold_events_from_splits(tmp_path / "nope", per)
    assert per_fold_events == []
    assert warnings and "缺失" in warnings[0]


def test_fold_events_reports_unknown_patients(tmp_path):
    per = _fake_event_stats([("A", "a", 1, 10.0)])
    split_dir = tmp_path / "tcga_aa"
    _write_splits(split_dir, [(["A"], ["A", "ZZZ"])])
    per_fold_events, per_fold_patients, warnings = fold_events_from_splits(split_dir, per)
    assert per_fold_events == [1]
    assert per_fold_patients == [2]
    assert any("未找到" in w for w in warnings)


# ---------------------------------------------------------------------------
# D2 候选口径：严格 landmark 事件数
# ---------------------------------------------------------------------------


def test_strict_landmark_events():
    per = _fake_event_stats(
        [
            ("A", "a", 1, 100.0),   # 事件在 landmark 前 -> 被排除
            ("B", "b", 1, 500.0),   # landmark 后的事件 -> 保留
            ("C", "c", 0, 900.0),   # 删失，不算事件
            ("D", "d", 1, None),    # 时间缺失 -> 不算
            ("E", "e", "1", 300.0),  # 字符串 event 兼容
        ]
    )
    assert strict_landmark_events(per, 0) == 3      # A(100) + B(500) + E(300)
    assert strict_landmark_events(per, 365) == 1    # 只剩 B(500)
    assert strict_landmark_events(per, 730) == 0
    assert strict_landmark_events(pd.DataFrame(), 0) == 0


def test_study_name_mapping():
    assert study_name_for("TCGA-BRCA") == "tcga_brca"
    assert study_name_for("TCGA_LIHC") == "tcga_lihc"
    assert study_name_for("MMRF") == "mmrf"
    assert study_name_for("CPTAC") == "cptac"


# ---------------------------------------------------------------------------
# manifest 行：D2 未确认时 effective_events_* 留空
# ---------------------------------------------------------------------------


def _record(**over):
    record = {
        "dataset": "TCGA-AA",
        "tier": "main",
        "tier_base": "main",
        "n_patients": 200,
        "n_event": 160,
        "event_rate": 0.8,
        "per_fold_events": [32, 32, 32, 32, 32],
        "degen_folds": 0,
        "degen_fold_indices": [],
        "epv_field_budget": 3,
        "rule_hits": ["R1"],
        "warnings": [],
    }
    record.update(over)
    return record


def test_manifest_row_keeps_effective_events_blank_with_todo():
    row = manifest_row(_record())
    assert list(row.keys()) == MANIFEST_COLUMNS
    assert row["effective_events_lm0"] == ""
    assert row["effective_events_lm365"] == ""
    assert row["effective_events_lm730"] == ""
    assert "TODO(D2)" in row["note"]
    assert "provisional(D1)" in row["note"]
    assert row["per_fold_events"] == "32|32|32|32|32"


def test_manifest_row_mmrf_note_mentions_d2():
    row = manifest_row(_record(dataset="MMRF"))
    assert "口径待 D2" in row["note"]


def test_manifest_row_records_downgrade_and_degen():
    row = manifest_row(
        _record(
            tier="excluded",
            tier_base="supplementary",
            rule_hits=["R3", "R5", "R7"],
            degen_folds=2,
            degen_fold_indices=[1, 4],
        )
    )
    assert "降级 supplementary->excluded" in row["note"]
    assert "退化折 2" in row["note"]
    assert row["rule_hits"] == "R3;R5;R7"


# ---------------------------------------------------------------------------
# 端到端：假数据树 → manifest.csv + profile.json（可重复）
# ---------------------------------------------------------------------------


def _fake_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "rawdata_stats" / "_shared").mkdir(parents=True)
    (root / "rawdata_stats" / "TCGA-AA").mkdir(parents=True)
    (root / "rawdata_stats" / "TCGA-BB").mkdir(parents=True)

    pd.DataFrame(
        [
            {"dataset": "TCGA-AA", "n_patients": 200, "n_event": 160, "n_censored": 40, "n_unknown": 0, "event_rate": 0.8},
            {"dataset": "TCGA-BB", "n_patients": 50, "n_event": 10, "n_censored": 40, "n_unknown": 0, "event_rate": 0.2},
        ]
    ).to_csv(root / "rawdata_stats/_shared/event_summary.csv", index=False)

    aa = pd.DataFrame(
        [{"submitter_id": f"A{i}", "case_id": f"a{i}", "event": 1 if i % 2 == 0 else 0, "ground_truth_time": 100.0 * (i + 1)}
         for i in range(10)]
    )
    aa.to_csv(root / "rawdata_stats/TCGA-AA/event_stats.csv", index=False)
    pd.DataFrame(
        [{"submitter_id": f"B{i}", "case_id": f"b{i}", "event": 1, "ground_truth_time": 500.0} for i in range(4)]
    ).to_csv(root / "rawdata_stats/TCGA-BB/event_stats.csv", index=False)

    splits = root / "Clinic_Analyzer" / "data" / "splits" / "5foldcv"
    _write_splits(splits / "tcga_aa", [([], ["A0", "A1"]), ([], ["A2", "A3"])])
    _write_splits(splits / "tcga_bb", [([], ["B0", "B1"])])

    (root / "datasets.json").write_text(
        json.dumps({"TCGA-AA": {}, "TCGA-BB": {}, "TCGA-CC": {}}), encoding="utf-8"
    )
    return root


def test_run_end_to_end_and_reproducible(tmp_path):
    root = _fake_project(tmp_path)
    out = tmp_path / "out"
    manifest_path, _ = run(project_root=root, out_dir=out, quiet=True)

    frame = pd.read_csv(manifest_path, keep_default_na=False)
    assert list(frame.columns) == MANIFEST_COLUMNS
    assert list(frame["dataset"]) == ["TCGA-AA", "TCGA-BB", "TCGA-CC"]

    by_dataset = frame.set_index("dataset")
    # TCGA-AA: n_event=160 -> 主集
    assert by_dataset.loc["TCGA-AA", "tier"] == "main"
    # TCGA-BB: n_event=10 -> 排除集
    assert by_dataset.loc["TCGA-BB", "tier"] == "excluded"
    # TCGA-CC: event_summary 中不存在 -> n_event=0 -> 排除集，且 note 记录缺失
    assert by_dataset.loc["TCGA-CC", "tier"] == "excluded"
    assert "event_summary.csv 中无该队列" in by_dataset.loc["TCGA-CC", "note"]
    # 所有行的 effective_events_* 均为空（D2 未确认）
    assert (frame["effective_events_lm0"] == "").all()

    profile = json.loads((out / "TCGA-AA_profile.json").read_text(encoding="utf-8"))
    assert profile["landmark"]["status"] == "todo_D2"
    assert profile["landmark"]["caliber"] is None
    assert profile["landmark"]["current_implementation"]["excludes_patients"] is False
    assert profile["n_event_in_splits"] == 2  # A0(event) + A2(event)
    assert profile["per_fold_events"] == [1, 1]

    first_manifest = manifest_path.read_bytes()
    first_profiles = {p.name: p.read_bytes() for p in out.glob("*_profile.json")}

    run(project_root=root, out_dir=out, quiet=True)
    assert manifest_path.read_bytes() == first_manifest
    for name, payload in first_profiles.items():
        assert (out / name).read_bytes() == payload


def test_run_marks_provisional_tier(tmp_path):
    root = _fake_project(tmp_path)
    out = tmp_path / "out"
    run(project_root=root, out_dir=out, quiet=True)
    frame = pd.read_csv(out / "manifest.csv", keep_default_na=False)
    assert frame["note"].str.contains("provisional").all()
