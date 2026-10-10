"""gt<=0 全局患者过滤(dataset_survival)的单元与构造级测试。

背景:用户决定(2026-10-05)将 ground_truth_time <= 0 的占位坑患者
(days_to_death=0 字面占位 / 负末次随访,见 z_notes/protocol/1_landmark/time_axis.md §2.3)
从所有实验臂中全局剔除。落点:
SurvivalDatasetFactory._drop_nonpositive_time_labels,读 label 后即过滤,
NaN 时间保留(镜像 src/manual_pipeline/landmark_labels.py 的 NaN 保留约定)。

运行方式(本文件需要 torch,SurvPGC 环境):
    /data/fangyuxuan/miniconda3/envs/SurvPGC/bin/python tests/test_gt_le_0_filter.py
或装 pytest 后:
    /data/fangyuxuan/miniconda3/envs/SurvPGC/bin/python -m pytest tests/test_gt_le_0_filter.py
无 torch 环境(pytest 收集)自动 skip。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import pytest
except ImportError:  # SurvPGC 环境无 pytest 时可独立运行(__main__)
    pytest = None

if pytest is not None:
    pytest.importorskip("torch")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "Clinic_Analyzer"))

from datasets.dataset_survival import SurvivalDatasetFactory


def _bare_factory(df: pd.DataFrame) -> SurvivalDatasetFactory:
    obj = object.__new__(SurvivalDatasetFactory)
    obj.label_data = df
    obj.label_file = "synthetic.csv"
    obj.label_col = "survival_months"
    obj.censorship_var = "censorship"
    obj.print_info = False
    return obj


def test_drop_nonpositive_keeps_nan():
    df = pd.DataFrame(
        {
            "case_id": ["c_pos", "c_ev0", "c_cen0", "c_neg", "c_nan"],
            "slide_id": ["s_pos", "s_ev0", "s_cen0", "s_neg", "s_nan"],
            "survival_months": [10.0, 0.0, 0.0, -0.03, np.nan],
            "censorship": [1, 0, 1, 1, 1],
        }
    )
    obj = _bare_factory(df)
    obj._drop_nonpositive_time_labels()
    assert list(obj.label_data["case_id"]) == ["c_pos", "c_nan"]  # NaN 时间保留
    assert obj.gt_le_0_summary["total_rows_before"] == 5
    assert obj.gt_le_0_summary["removed_rows"] == 3
    assert obj.gt_le_0_summary["kept_rows"] == 2
    assert {r["case_id"] for r in obj.gt_le_0_removed_rows} == {"c_ev0", "c_cen0", "c_neg"}


def test_drop_nonpositive_none():
    df = pd.DataFrame(
        {
            "case_id": ["c1", "c2"],
            "slide_id": ["s1", "s2"],
            "survival_months": [10.0, 20.0],
            "censorship": [0, 1],
        }
    )
    obj = _bare_factory(df)
    obj._drop_nonpositive_time_labels()
    assert len(obj.label_data) == 2
    assert obj.gt_le_0_summary["removed_rows"] == 0
    assert obj.gt_le_0_removed_rows == []


def test_factory_construction_drops_gt_le_0(tmp_path):
    """构造级验证:完整 SurvivalDatasetFactory(mlp_clinic_flatten,clinic-only)读 label 后即过滤。"""
    label_csv = tmp_path / "label.csv"
    rows = []
    # 正时间:事件 6 个不同值(qcut 要求)+ 删失若干
    for i, t in enumerate([6.0, 12.0, 24.0, 36.0, 48.0, 60.0]):
        rows.append((f"case_ev{i}", f"slide_ev{i}.svs", t, 0))
    for i, t in enumerate([8.0, 18.0, 30.0, 42.0, 54.0, 66.0]):
        rows.append((f"case_cen{i}", f"slide_cen{i}.svs", t, 1))
    # gt<=0 占位坑行(构造后应全部消失)
    rows.append(("case_ev0", "slide_ev0.svs", 0.0, 0))
    rows.append(("case_cen0", "slide_cen0.svs", 0.0, 1))
    rows.append(("case_neg", "slide_neg.svs", -0.03285, 1))
    pd.DataFrame(rows, columns=["case_id", "slide_id", "survival_months", "censorship"]).to_csv(
        label_csv, index=False
    )

    clinical_csv = tmp_path / "clinical.csv"
    pd.DataFrame({"dummy": [1]}).to_csv(clinical_csv)

    fac = SurvivalDatasetFactory(
        study="test_study",
        label_file=str(label_csv),
        omics_dir=None,
        seed=0,
        print_info=False,
        n_bins=4,
        label_col="survival_months",
        eps=1e-6,
        num_patches=4096,
        type_of_pathway="combine",
        clinical_file=str(clinical_csv),
        modality="mlp_clinic_flatten",
        gene_dir=None,
    )
    times = pd.to_numeric(fac.label_data["survival_months"], errors="coerce")
    assert (times > 0).all()
    assert fac.gt_le_0_summary["total_rows_before"] == 15
    assert fac.gt_le_0_summary["removed_rows"] == 3
    assert fac.gt_le_0_summary["kept_rows"] == 12
    assert {r["case_id"] for r in fac.gt_le_0_removed_rows} == {"case_ev0", "case_cen0", "case_neg"}


if __name__ == "__main__":
    import tempfile

    test_drop_nonpositive_keeps_nan()
    test_drop_nonpositive_none()
    with tempfile.TemporaryDirectory() as d:
        test_factory_construction_drops_gt_le_0(Path(d))
    print("gt_le_0 filter tests OK")
