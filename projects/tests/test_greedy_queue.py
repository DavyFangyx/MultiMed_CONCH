from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from greedy.cli import build_parser, resolve_dataset_list
from greedy.queue import claim_job, enqueue_jobs, load_job


def _args(tmp_path: Path):
    return build_parser().parse_args(
        [
            "--dataset",
            "TCGA-BRCA,TCGA-READ,TCGA_LIHC",
            "--landmark_time",
            "none",
            "--queue_root",
            str(tmp_path / "greedy"),
        ]
    )


def test_scheduler_generates_one_conf_per_dataset(tmp_path):
    args = _args(tmp_path)
    names = resolve_dataset_list(args)
    queued = enqueue_jobs(args, names)
    created = {p.name.split("__", 1)[1].removesuffix(".conf") for p in queued["created"]}
    assert created == {f"{name}__landmark_none" for name in names}
    again = enqueue_jobs(args, names)
    assert again["created"] == []
    assert len(again["existing"]) == 3


def test_two_gpus_cannot_claim_the_same_running_dataset(tmp_path):
    args = _args(tmp_path)
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


def test_longitudinal_queue_root_is_separate(tmp_path):
    args = build_parser().parse_args(
        [
            "--dataset",
            "TCGA-BRCA",
            "--landmark_time",
            "none",
            "--experiment",
            "longitudinal",
        ]
    )
    from greedy.queue import DEFAULT_QUEUE_ROOT, queue_root_from_args

    root = queue_root_from_args(args)
    assert root == DEFAULT_QUEUE_ROOT.parent / "longitudinal"
    assert root != DEFAULT_QUEUE_ROOT
    queued = enqueue_jobs(args, ["TCGA-BRCA"], root=tmp_path / "longitudinal")
    created = {p.name.split("__", 1)[1].removesuffix(".conf") for p in queued["created"]}
    assert created == {"TCGA-BRCA__landmark_none"}
    payload = load_job(queued["created"][0])
    assert payload["args"]["experiment"] == "longitudinal"


def test_scheduler_generates_one_conf_per_dataset_and_landmark(tmp_path):
    args = build_parser().parse_args(
        [
            "--dataset",
            "TCGA-BRCA,TCGA-READ",
            "--landmark_time",
            "none,365",
            "--queue_root",
            str(tmp_path / "greedy"),
        ]
    )
    queued = enqueue_jobs(args, resolve_dataset_list(args))
    created = {p.name.split("__", 1)[1].removesuffix(".conf") for p in queued["created"]}
    assert created == {
        "TCGA-BRCA__landmark_none",
        "TCGA-BRCA__landmark_365",
        "TCGA-READ__landmark_none",
        "TCGA-READ__landmark_365",
    }
    payload = load_job(queued["created"][0])
    assert payload["args"]["landmark_time"] in {"none", "365"}
    assert payload["landmark_tag"].startswith("landmark_")


def test_scheduler_landmark_all_scans_field_bank_parent(tmp_path, monkeypatch):
    from common.paths import dataset_field_bank_dir

    bank_parent = tmp_path / "field_bank" / "prompt"
    for tag in ("landmark_0", "landmark_365", "landmark_none"):
        (bank_parent / tag).mkdir(parents=True)

    def fake_dir(dataset_name, encoding="prompt", landmark_tag=None, experiment=None):
        return bank_parent / (landmark_tag or "landmark_none")

    monkeypatch.setattr("common.paths.dataset_field_bank_dir", fake_dir)
    args = build_parser().parse_args(
        [
            "--dataset",
            "TCGA-BRCA",
            "--landmark_time",
            "all",
            "--queue_root",
            str(tmp_path / "greedy"),
        ]
    )
    queued = enqueue_jobs(args, ["TCGA-BRCA"])
    created = {p.name.split("__", 1)[1].removesuffix(".conf") for p in queued["created"]}
    assert created == {
        "TCGA-BRCA__landmark_0",
        "TCGA-BRCA__landmark_365",
        "TCGA-BRCA__landmark_none",
    }
