from pathlib import Path
import csv
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common.paths import PROJECT_ROOT, dataset_univariate_dir
from greedy.queue import DEFAULT_QUEUE_ROOT, DEFAULT_UNIVARIATE_QUEUE_ROOT, claim_job, enqueue_jobs, load_job, queue_root_from_args
from greedy.univariate_cli import (
    CSV_COLUMNS,
    evaluate_all_fields,
    make_parser,
    resolve_dataset_list,
    write_univariate_outputs,
)


FIELDS = ["f0", "f1", "f2", "f3"]
SCORES = [0.51, 0.67, 0.60, 0.55]


class StubUnivariateEvaluator:
    def __init__(self, fields, scores, fail_idx=None):
        self.fields = list(fields)
        self.dataset = "TCGA_LIHC"
        self.scores = list(scores)
        self.fail_idx = fail_idx
        self.calls = []

    def evaluate(self, subset_idx):
        idx = [int(i) for i in list(subset_idx)]
        self.calls.append(idx)
        if not idx:
            return {"c_index_mean": 0.5, "c_index_std": 0.0, "per_fold": [0.5], "empty": True, "scheme": "G0_empty"}
        field_idx = idx[0]
        if self.fail_idx is not None and field_idx == self.fail_idx:
            raise RuntimeError("boom")
        mean = float(self.scores[field_idx])
        return {
            "c_index_mean": mean,
            "c_index_std": 0.01,
            "per_fold": [mean, mean - 0.01, mean + 0.01, mean, mean],
            "scheme": f"G1_{field_idx:02d}",
            "clinic_dir": f"/tmp/subset/{field_idx}",
        }


def test_dataset_univariate_dir_prompt():
    path = dataset_univariate_dir("TCGA_LIHC", "prompt", "landmark_365")
    assert path == PROJECT_ROOT / "outputs" / "TCGA_LIHC" / "univariate" / "prompt" / "landmark_365"
    assert path.as_posix().endswith("outputs/TCGA_LIHC/univariate/prompt/landmark_365")


def test_parser_defaults_and_flags():
    parser = make_parser()
    args = parser.parse_args(["--dataset", "TCGA_LIHC", "--landmark_time", "none"])
    assert args.workers == 8
    assert args.modality == "mlp_clinic_flatten"
    assert args.encoding == "prompt"
    assert args.seed == 0
    assert args.experiment == ""
    flags = {action.option_strings[0] for action in parser._actions if action.option_strings}
    assert "--init_field" not in flags
    assert "--outer_modalities" not in flags
    assert "--min_delta" not in flags
    assert "--patience" not in flags
    assert "--max_steps" not in flags
    assert "--queue_root" in flags
    assert not hasattr(args, "init_field")
    assert not hasattr(args, "outer_modalities")


def test_stub_evaluator_writes_sorted_singleton_csv(tmp_path):
    evaluator = StubUnivariateEvaluator(FIELDS, SCORES)
    rows = evaluate_all_fields(evaluator, FIELDS, workers=2)
    assert [row["field"] for row in rows] == ["f1", "f2", "f3", "f0"]
    assert all(int(row["n_fields"]) == 1 for row in rows)
    assert all(row["status"] == "ok" for row in rows)
    assert evaluator.calls == [[0], [1], [2], [3]] or set(tuple(x) for x in evaluator.calls) == {(0,), (1,), (2,), (3,)}
    out_dir = tmp_path / "univariate"
    write_univariate_outputs(
        out_dir,
        rows,
        dataset="TCGA_LIHC",
        encoding="prompt",
        modality="mlp_clinic_flatten",
        workers=8,
        seed=0,
        field_bank_dir="/tmp/bank",
        split_dir="/tmp/splits",
    )
    csv_path = out_dir / "field_cindex.csv"
    with open(csv_path, newline="", encoding="utf-8") as f:
        table = list(csv.DictReader(f))
    assert list(table[0].keys()) == CSV_COLUMNS
    assert [row["field"] for row in table] == ["f1", "f2", "f3", "f0"]
    assert all(row["n_fields"] == "1" for row in table)
    assert "scheme" not in table[0]
    assert "clinic_dir" not in table[0]
    assert "error" not in table[0]
    config = json.loads((out_dir / "run_config.json").read_text())
    assert config["prefer_val"] is True
    assert config["n_fields"] == 4
    assert config["n_ok"] == 4
    assert config["n_error"] == 0
    assert config["modality"] == "mlp_clinic_flatten"
    assert config["field_errors"] == []


def test_field_error_does_not_abort_remaining_rows(tmp_path):
    evaluator = StubUnivariateEvaluator(FIELDS, SCORES, fail_idx=2)
    rows = evaluate_all_fields(evaluator, FIELDS, workers=3)
    by_field = {row["field"]: row for row in rows}
    assert by_field["f2"]["status"] == "error"
    assert by_field["f2"]["error"] == "boom"
    assert by_field["f2"]["c_index_mean"] == ""
    assert [row["field"] for row in rows if row.get("status") == "ok"] == ["f1", "f3", "f0"]
    assert rows[-1]["field"] == "f2"
    out_dir = tmp_path / "univariate"
    write_univariate_outputs(
        out_dir,
        rows,
        dataset="TCGA_LIHC",
        encoding="prompt",
        modality="mlp_clinic_flatten",
        workers=8,
        seed=0,
        field_bank_dir="/tmp/bank",
        split_dir="/tmp/splits",
    )
    with open(out_dir / "field_cindex.csv", newline="", encoding="utf-8") as f:
        table = list(csv.DictReader(f))
    assert [row["field"] for row in table] == ["f1", "f3", "f0", "f2"]
    assert table[-1]["status"] == "error"
    assert table[-1]["c_index_mean"] == ""
    assert "error" not in table[-1]
    config = json.loads((out_dir / "run_config.json").read_text())
    assert config["n_ok"] == 3
    assert config["n_error"] == 1
    assert config["field_errors"] == [
        {
            "field": "f2",
            "field_idx": 2,
            "error": "boom",
            "scheme": "G1_c81e728d9d",
            "clinic_dir": "",
        }
    ]


def _queue_args(tmp_path: Path, extra=None):
    argv = [
        "--dataset",
        "TCGA-BRCA,TCGA-READ,TCGA_LIHC",
        "--landmark_time",
        "none",
        "--queue_root",
        str(tmp_path / "univariate"),
    ]
    if extra:
        argv.extend(extra)
    args = make_parser().parse_args(argv)
    args.queue_kind = "univariate"
    return args


def test_univariate_queue_is_separate_from_greedy():
    args = make_parser().parse_args(["--dataset", "TCGA_LIHC", "--landmark_time", "none"])
    args.queue_kind = "univariate"
    root = queue_root_from_args(args)
    assert root == DEFAULT_UNIVARIATE_QUEUE_ROOT
    assert root != DEFAULT_QUEUE_ROOT
    args.experiment = "longitudinal"
    root = queue_root_from_args(args)
    assert root == DEFAULT_UNIVARIATE_QUEUE_ROOT.parent / "longitudinal_univariate"


def test_two_gpus_cannot_claim_the_same_univariate_dataset(tmp_path):
    args = _queue_args(tmp_path)
    queued = enqueue_jobs(args, resolve_dataset_list(args))
    root = queued["root"]
    key = queued["job_key"]
    os.environ["CUDA_VISIBLE_DEVICES"] = "5"
    first = claim_job(root, key)
    os.environ["CUDA_VISIBLE_DEVICES"] = "6"
    second = claim_job(root, key)
    assert first is not None and second is not None
    assert load_job(first)["dataset"] != load_job(second)["dataset"]
    assert load_job(first)["cuda_visible_devices"] == "5"
    assert load_job(second)["cuda_visible_devices"] == "6"
    still_queued = {p.name for p in (root / "queue").glob("*.conf")}
    running = {p.name for p in (root / "running").glob("*.conf")}
    assert first.name in running and second.name in running
    assert first.name not in still_queued and second.name not in still_queued


if __name__ == "__main__":
    import tempfile
    test_dataset_univariate_dir_prompt()
    test_parser_defaults_and_flags()
    test_univariate_queue_is_separate_from_greedy()
    with tempfile.TemporaryDirectory() as tmp:
        test_stub_evaluator_writes_sorted_singleton_csv(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_field_error_does_not_abort_remaining_rows(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_two_gpus_cannot_claim_the_same_univariate_dataset(Path(tmp))
    print("ok")
