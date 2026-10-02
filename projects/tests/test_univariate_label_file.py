"""S5: univariate landmark 派生 label 解析（与 Test_1b 臂 B 同患者集）。"""

import argparse
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from greedy.univariate_cli import resolve_univariate_label_file


def _args(**overrides):
    defaults = {
        "label_file": None,
        "landmark_labels_dir": str(ROOT / "results" / "A_manual_landmark" / "labels"),
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_derives_study_label_for_landmark(tmp_path):
    (tmp_path / "tcga_brca__landmark_0.csv").write_text("x\n")
    args = _args(landmark_labels_dir=str(tmp_path))
    got = resolve_univariate_label_file(args, Path(tmp_path / "tcga_brca"), "landmark_0")
    assert got == str(tmp_path / "tcga_brca__landmark_0.csv")


def test_landmark_none_returns_none(tmp_path):
    args = _args(landmark_labels_dir=str(tmp_path))
    assert resolve_univariate_label_file(args, Path(tmp_path / "tcga_brca"), "landmark_none") is None


def test_missing_derived_label_raises(tmp_path):
    args = _args(landmark_labels_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError, match="landmark 派生 label"):
        resolve_univariate_label_file(args, Path(tmp_path / "tcga_brca"), "landmark_0")


def test_explicit_label_file_override(tmp_path):
    lab = tmp_path / "custom.csv"
    lab.write_text("x\n")
    args = _args(label_file=str(lab), landmark_labels_dir=str(tmp_path))
    assert resolve_univariate_label_file(args, Path(tmp_path / "tcga_brca"), "landmark_0") == str(lab)


def test_explicit_label_file_missing_raises(tmp_path):
    args = _args(label_file=str(tmp_path / "nope.csv"), landmark_labels_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError, match="--label_file 不存在"):
        resolve_univariate_label_file(args, Path(tmp_path / "tcga_brca"), "landmark_0")


def test_evaluator_stores_and_extends_label_file(tmp_path):
    from greedy.clinic_evaluator import ClinicSubsetEvaluator

    evaluator = ClinicSubsetEvaluator(
        dataset="TCGA-BRCA",
        fields=["demographic.race"],
        splits=None,
        field_bank_dir=str(tmp_path / "fb"),
        landmark_tag="landmark_0",
        label_file=str(tmp_path / "labels" / "tcga_brca__landmark_0.csv"),
    )
    assert evaluator.label_file == Path(tmp_path) / "labels" / "tcga_brca__landmark_0.csv"
