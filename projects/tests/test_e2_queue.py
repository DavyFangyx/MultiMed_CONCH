from argparse import Namespace
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import run_e2_selection_queue
from selection.queue import enqueue, move


def _args(root):
    return Namespace(
        dataset="TCGA-CHOL",
        landmark_time="0",
        algo="ANCHOR_TIMING",
        seed="0",
        queue_root=str(root),
        poll_seconds=1.0,
        max_jobs=0,
    )


def test_failed_e2_job_is_requeued_but_done_job_is_not(tmp_path):
    args = _args(tmp_path)
    first = enqueue(args, ["TCGA-CHOL"], ["0"])
    queued = first["created"][0]
    failed = move(queued, "failed")

    retried = enqueue(args, ["TCGA-CHOL"], ["0"])

    assert retried["created"] == [tmp_path / "queue" / failed.name]
    assert not failed.exists()
    done = move(retried["created"][0], "done")

    unchanged = enqueue(args, ["TCGA-CHOL"], ["0"])

    assert unchanged["created"] == []
    assert unchanged["existing"] == [done]


def test_command_maps_legacy_inner_modality_key():
    job = {
        "args": {
            "dataset": "TCGA-CHOL",
            "landmark_time": "0",
            "algo": "ANCHOR",
            "anchor_p": 12,
            "inner_modality": "clinic_cox",
        }
    }
    command = run_e2_selection_queue._command(job)
    assert "--inner_modality" not in command
    assert "--anchor_p" in command
    idx = command.index("--inner_analyzer")
    assert command[idx + 1] == "clinic_cox"


def test_enqueue_job_key_differs_per_inner_analyzer(tmp_path):
    args_a = _args(tmp_path)
    args_a.inner_analyzer = "mlp_clinic_flatten"
    args_b = Namespace(**vars(args_a))
    args_b.inner_analyzer = "clinic_cox"
    first = enqueue(args_a, ["TCGA-CHOL"], ["0"])
    second = enqueue(args_b, ["TCGA-CHOL"], ["0"])
    assert first["job_key"] != second["job_key"]
    assert second["created"]
    assert "clinic_cox" in Path(second["created"][0]).read_text(encoding="utf-8")
