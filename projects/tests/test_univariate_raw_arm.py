"""Test_1a off 臂（raw 变体，取值 mask 关闭）CLI 契约测试。

覆盖：
  ① 新增参数默认值（--extraction_mask / --field_bank_root / --embeddings_root / --results_dir / --label_tag）；
  ② resolve_extraction_mask 的 auto/on/off 语义与冲突报错；
  ③ resolve_patient_label_tag 的 raw 臂守卫（必须显式声明患者集，否则两臂患者集会漂）；
  ④ resolve_field_bank_dir 的优先级（direct > root > 规范路径）；
  ⑤ assert_field_bank_mask 双向防呆（mask 状态与 field bank landmark_policy 必须一致）；
  ⑥ 队列 job_key：raw 臂与 t0 臂不同（不撞 t0 的 done 桶），worker-local 参数不影响 key；
  ⑦ 患者集解析（label_tag=landmark_0）与 raw 臂输出目录命名空间。
"""

from pathlib import Path
import argparse
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common.paths import PROJECT_ROOT, dataset_field_bank_dir
from greedy.queue import enqueue_jobs, job_key_from_args
from greedy.univariate_cli import (
    assert_field_bank_mask,
    make_parser,
    resolve_dataset_list,
    resolve_extraction_mask,
    resolve_field_bank_dir,
    resolve_patient_label_tag,
    resolve_univariate_label_file,
    univariate_out_dir,
)


RAW_ARGV = [
    "--dataset",
    "TCGA-ACC",
    "--landmark_time",
    "none",
    "--extraction_mask",
    "off",
    "--label_tag",
    "landmark_0",
    "--field_bank_root",
    "outputs/_raw",
    "--embeddings_root",
    "outputs/_raw",
    "--results_dir",
    "results/univariate_raw",
    "--encoding",
    "prompt",
    "--analyzer",
    "mlp_clinic_flatten",
    "--seed",
    "0",
    "--workers",
    "8",
    "--queue_root",
    "Clinic_Analyzer/configs/univariate_raw",
]


def parse(argv):
    args = make_parser().parse_args(argv)
    args.queue_kind = "univariate"
    return args


def ns(**kw):
    base = {
        "extraction_mask": "auto",
        "label_tag": None,
        "label_file": None,
        "landmark_labels_dir": None,
        "field_bank_dir": None,
        "field_bank_root": None,
        "embeddings_root": None,
        "results_dir": None,
        "experiment": "",
    }
    base.update(kw)
    return argparse.Namespace(**base)


def test_parser_defaults_for_raw_arm_args():
    args = parse(["--dataset", "TCGA-ACC", "--landmark_time", "0"])
    assert args.extraction_mask == "auto"
    assert args.field_bank_root is None
    assert args.embeddings_root is None
    assert args.results_dir is None
    assert args.label_tag is None


def test_parser_accepts_raw_arm_argv():
    args = parse(RAW_ARGV)
    assert args.extraction_mask == "off"
    assert args.landmark_time == "none"
    assert args.label_tag == "landmark_0"
    assert args.field_bank_root == "outputs/_raw"
    assert args.results_dir == "results/univariate_raw"


def test_resolve_extraction_mask_follows_tag_by_default():
    assert resolve_extraction_mask(ns(), "landmark_0") == "on"
    assert resolve_extraction_mask(ns(), "landmark_365") == "on"
    assert resolve_extraction_mask(ns(), "landmark_none") == "off"


def test_resolve_extraction_mask_explicit_and_conflicts():
    assert resolve_extraction_mask(ns(extraction_mask="off"), "landmark_none") == "off"
    assert resolve_extraction_mask(ns(extraction_mask="on"), "landmark_0") == "on"
    with pytest.raises(ValueError, match="冲突"):
        resolve_extraction_mask(ns(extraction_mask="off"), "landmark_0")
    with pytest.raises(ValueError, match="冲突"):
        resolve_extraction_mask(ns(extraction_mask="on"), "landmark_none")
    with pytest.raises(ValueError, match="auto/on/off"):
        resolve_extraction_mask(ns(extraction_mask="raw"), "landmark_none")


def test_raw_arm_requires_explicit_patient_set():
    with pytest.raises(ValueError, match="必须显式声明患者集"):
        resolve_patient_label_tag(ns(extraction_mask="off"), "landmark_none", "off")
    got = resolve_patient_label_tag(
        ns(extraction_mask="off", label_tag="landmark_0"), "landmark_none", "off"
    )
    assert got == "landmark_0"


def test_raw_arm_label_file_override_satisfies_patient_set():
    got = resolve_patient_label_tag(
        ns(extraction_mask="off", label_file="/tmp/labels.csv"), "landmark_none", "off"
    )
    assert got == "landmark_none"


def test_mask_on_arm_label_tag_follows_tag():
    assert resolve_patient_label_tag(ns(extraction_mask="auto"), "landmark_0", "on") == "landmark_0"
    assert resolve_patient_label_tag(ns(extraction_mask="auto"), "landmark_365", "on") == "landmark_365"
    with pytest.raises(ValueError):
        resolve_patient_label_tag(ns(label_tag="landmark_raw"), "landmark_0", "on")


def test_resolve_field_bank_dir_precedence():
    explicit = "/data/custom/bank"
    assert (
        resolve_field_bank_dir(ns(field_bank_dir=explicit), "TCGA-ACC", "prompt", "landmark_none", "")
        == Path(explicit)
    )
    rooted = resolve_field_bank_dir(
        ns(field_bank_root="outputs/_raw"), "TCGA-ACC", "prompt", "landmark_none", ""
    )
    assert rooted == Path("outputs/_raw") / "TCGA-ACC" / "field_bank" / "prompt" / "landmark_none"
    canonical = resolve_field_bank_dir(ns(), "TCGA-ACC", "prompt", "landmark_none", "")
    assert canonical == dataset_field_bank_dir("TCGA-ACC", "prompt", "landmark_none")
    with pytest.raises(ValueError):
        resolve_field_bank_dir(ns(field_bank_root="outputs/_raw"), "TCGA-ACC", "bad_encoding", "landmark_none", "")


def test_assert_field_bank_mask_both_directions():
    assert_field_bank_mask(Path("/x"), "off", {"landmark_policy": "off"})
    assert_field_bank_mask(Path("/x"), "on", {"landmark_policy": "t_hi_le_landmark_time"})
    assert_field_bank_mask(Path("/x"), "off", None)
    assert_field_bank_mask(Path("/x"), "on", {})
    with pytest.raises(ValueError, match="landmark_policy"):
        assert_field_bank_mask(Path("/x"), "off", {"landmark_policy": "t_hi_le_landmark_time"})
    with pytest.raises(ValueError, match="landmark_policy=off"):
        assert_field_bank_mask(Path("/x"), "on", {"landmark_policy": "off"})


def test_raw_and_t0_job_keys_are_distinct():
    t0 = parse(["--dataset", "TCGA-ACC", "--landmark_time", "0", "--analyzer", "mlp_clinic_flatten"])
    raw = parse(RAW_ARGV)
    raw.landmark_tag = "landmark_none"
    assert job_key_from_args(t0) != job_key_from_args(raw)


def test_raw_job_key_ignores_worker_local_args():
    a = parse(RAW_ARGV)
    b = parse(RAW_ARGV)
    b.workers = 2
    b.queue_root = "/tmp/other_queue"
    b.device = "3"
    assert job_key_from_args(a) == job_key_from_args(b)


def test_raw_enqueue_uses_landmark_none_suffix_and_separate_root(tmp_path):
    argv = list(RAW_ARGV)
    argv[argv.index("--queue_root") + 1] = str(tmp_path / "univariate_raw")
    args = parse(argv)
    args.landmark_tag = "landmark_none"
    args.landmark_time = "none"
    queued = enqueue_jobs(args, ["TCGA-ACC"])
    assert queued["root"] == tmp_path / "univariate_raw"
    names = [p.name for p in queued["created"]]
    assert len(names) == 1 and names[0].endswith("__TCGA-ACC__landmark_none.conf")
    again = enqueue_jobs(args, ["TCGA-ACC"])
    assert not again["created"] and len(again["existing"]) == 1


def test_raw_arm_patient_set_uses_label_tag(tmp_path):
    args = parse(RAW_ARGV)
    labels = tmp_path / "labels"
    labels.mkdir()
    (labels / "tcga_acc__landmark_0.csv").write_text("patient_id\nTCGA-OR-A5J1\n", encoding="utf-8")
    args.landmark_labels_dir = str(labels)
    mask_state = resolve_extraction_mask(args, "landmark_none")
    label_tag = resolve_patient_label_tag(args, "landmark_none", mask_state)
    assert mask_state == "off" and label_tag == "landmark_0"
    got = resolve_univariate_label_file(args, tmp_path / "tcga_acc", label_tag)
    assert got == str(labels / "tcga_acc__landmark_0.csv")


def test_raw_arm_output_namespace_is_separate():
    args = parse(RAW_ARGV)
    out_dir = univariate_out_dir(args, "TCGA-ACC", "prompt", "landmark_none", "", "mlp_clinic_flatten")
    assert out_dir == Path("results/univariate_raw") / "univariate/prompt/landmark_none/TCGA-ACC/mlp_clinic_flatten"
    t0 = parse(["--dataset", "TCGA-ACC", "--landmark_time", "0", "--analyzer", "mlp_clinic_flatten"])
    t0_dir = univariate_out_dir(t0, "TCGA-ACC", "prompt", "landmark_0", "", "mlp_clinic_flatten")
    assert t0_dir == PROJECT_ROOT / "results" / "univariate" / "prompt" / "landmark_0" / "TCGA-ACC" / "mlp_clinic_flatten"
    assert t0_dir != out_dir
    assert "landmark_0" not in out_dir.parts and "landmark_none" in out_dir.parts


def test_raw_dataset_list_matches_tcga_registry():
    args = parse(["--dataset", "all", "--landmark_time", "none"])
    names = resolve_dataset_list(args)
    tcga = [n for n in names if n.startswith("TCGA-") or n.startswith("TCGA_")]
    assert len(tcga) == 33
    assert "TCGA_LIHC" in tcga
