"""Test_6 截断预算:cap 数学 + queue 下划线 flag round-trip。"""

from argparse import Namespace
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import run_selection_queue
from selection.config import budget_cap_for
from selection.queue import enqueue


def test_budget_cap_for_full_budget_when_no_cap():
    assert budget_cap_for(38) == 38 * 39 // 2 == 741
    assert budget_cap_for(38, None) == 741


def test_budget_cap_for_truncates_at_cap():
    assert budget_cap_for(19, 500) == 190   # B=190 < 500 不截
    assert budget_cap_for(30, 500) == 465   # B=465 < 500 不截
    assert budget_cap_for(38, 500) == 500   # B=741 → 500
    assert budget_cap_for(45, 500) == 500   # B=1035 → 500


def test_budget_cap_for_rejects_negative_cap():
    with pytest.raises(ValueError):
        budget_cap_for(10, -1)


def _args(root):
    return Namespace(
        dataset="TCGA-GBM",
        landmark_time="0",
        algo="A1_random",
        stop_mode="gain_only",
        seed="0",
        budget_cap=500,
        queue_root=str(root),
        poll_seconds=1.0,
        max_jobs=0,
    )


def test_queue_command_roundtrip_keeps_underscore_budget_cap_flag(tmp_path):
    """_command 按 vars(args) 键重建 --{key};budget_cap 必须下划线拼写才能被主脚本识别。"""
    args = _args(tmp_path)
    queued = enqueue(args, ["TCGA-GBM"], ["0"])
    job = (tmp_path / "queue" / queued["created"][0].name).read_text(encoding="utf-8")
    assert '"budget_cap": 500' in job

    import json
    command = run_selection_queue._command(json.loads(job))
    assert "--budget_cap" in command
    assert command[command.index("--budget_cap") + 1] == "500"
    assert "--budget-cap" not in command


def test_queue_skips_none_budget_cap(tmp_path):
    args = _args(tmp_path)
    args.budget_cap = None
    queued = enqueue(args, ["TCGA-GBM"], ["0"])
    import json
    job = json.loads((tmp_path / "queue" / queued["created"][0].name).read_text(encoding="utf-8"))
    command = run_selection_queue._command(job)
    assert "--budget_cap" not in command


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in list(globals().items()):
            if name.startswith("test_"):
                fn(Path(tmp))
    print("ok")
