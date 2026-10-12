"""患者级前置过滤(2026-10-09 用户拍板):字段级预处理之前的 label 患者集收敛。

权威患者集 = Clinic_Analyzer label metadata;字段链(stats/filter/bank/baseline/
hgcn)的病例加载一律收敛到该患者集,gt≤0 等不可靠患者在字段级统计/编码之前剔除。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common.patient_set import (
    display_to_study,
    label_patient_ids,
    restrict_cases_to_label_patients,
)


def test_display_to_study_mapping():
    assert display_to_study("TCGA-COAD") == "tcga_coad"
    assert display_to_study("TCGA_LIHC") == "tcga_lihc"
    assert display_to_study("TCGA-UNKNOWN") == "tcga_unknown"


def test_label_patients_and_restrict(tmp_path: Path):
    meta = tmp_path / "meta.csv"
    pd.DataFrame({"case_id": ["P1", "P2"]}).to_csv(meta, index=False)

    cases = [
        {"submitter_id": "P1", "field": "a"},
        {"submitter_id": "P3", "field": "b"},  # 不在 label 患者集(如 gt≤0 剔除)
    ]
    # analyzer_dir 语义 = Clinic_Analyzer 根目录 → data/datasets_csv/metadata 下找
    analyzer = tmp_path / "Clinic_Analyzer"
    (analyzer / "data" / "datasets_csv" / "metadata").mkdir(parents=True)
    meta.rename(analyzer / "data" / "datasets_csv" / "metadata" / "tcga_x.csv")

    ids = label_patient_ids("TCGA-X", analyzer_dir=analyzer)
    assert ids == {"P1", "P2"}
    kept, stats = restrict_cases_to_label_patients(cases, "TCGA-X", analyzer_dir=analyzer, quiet=True)
    assert [c["submitter_id"] for c in kept] == ["P1"]
    assert stats["n_dropped"] == 1 and stats["dropped_ids"] == ["P3"]

    with pytest.raises(FileNotFoundError):
        label_patient_ids("TCGA-NOPE", analyzer_dir=analyzer)
