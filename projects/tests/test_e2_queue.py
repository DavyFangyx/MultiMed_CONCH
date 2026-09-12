from argparse import Namespace
from pathlib import Path
import sys


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

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
