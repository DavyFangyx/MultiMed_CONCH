"""Test_3 搜索队列助手测试：job_key 同源性 / conf 命名 / recover / retry / 占用恢复。

job_key 由 drainer（scripts/run_e2_selection_queue.py）的 parser 全字段哈希决定——
本测试锁定「助手与 drainer 逐字段同源」，防止手抄默认值漂移导致 conf 孤儿。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import Test_3_common as C  # noqa: E402
import Test_3_search_queue as Q  # noqa: E402
import run_e2_selection_queue  # noqa: E402
from selection.queue import enqueue, move  # noqa: E402


def test_job_args_parity_with_drainer_parser():
    args = Q._job_args("TCGA-LAML")
    ref = run_e2_selection_queue.parser().parse_args(Q._runner_argv("TCGA-LAML")[2:])
    assert vars(args) == vars(ref)          # 同源 parser：逐字段（含 workers 等默认值）一致
    assert args.dataset == "TCGA-LAML"
    assert args.landmark_time == "0" and args.algo == C.ALGO and args.seed == "0"
    assert args.inner_analyzer == C.ANALYZER
    assert args.out == str(C.search_dir("TCGA-LAML"))


def test_conf_name_and_enqueue_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "QUEUE_ROOT", tmp_path)
    args = Q._job_args("TCGA-LAML")
    first = enqueue(args, ["TCGA-LAML"], ["0"], root=tmp_path)
    created = first["created"][0]
    assert created.name == f"{first['job_key']}__TCGA-LAML__landmark_0.conf"
    assert Q.conf_exists("TCGA-LAML") == "queue"
    assert Q.conf_path("TCGA-LAML") == created

    again = enqueue(args, ["TCGA-LAML"], ["0"], root=tmp_path)
    assert again["created"] == [] and [str(p) for p in again["existing"]] == [str(created)]

    move(created, "running")
    assert Q.conf_exists("TCGA-LAML") == "running"
    assert Q.conf_path("TCGA-LAML", "running") == tmp_path / "running" / created.name


def _seed_running(tmp_path, dataset: str, *, claimed_pid: int, gpu: str = "") -> Path:
    args = Q._job_args(dataset)
    result = enqueue(args, [dataset], ["0"], root=tmp_path)
    running = move(result["created"][0], "running")
    job = json.loads(running.read_text(encoding="utf-8"))
    job.update({"claimed_pid": claimed_pid, "cuda_visible_devices": gpu, "claimed_at": "t"})
    running.write_text(json.dumps(job) + "\n", encoding="utf-8")
    return running


def test_recover_requeues_only_dead_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "QUEUE_ROOT", tmp_path)
    dead = _seed_running(tmp_path, "TCGA-LAML", claimed_pid=999_999_999)
    alive = _seed_running(tmp_path, "TCGA-COAD", claimed_pid=os.getpid())
    assert Q.conf_exists("TCGA-LAML") == "running"
    recovered = Q.cmd_recover(["TCGA-LAML", "TCGA-COAD"])
    assert recovered == 1
    assert Q.conf_exists("TCGA-LAML") == "queue"
    assert Q.conf_exists("TCGA-COAD") == "running"        # 活着的 claim 不动
    job = json.loads((tmp_path / "queue" / dead.name).read_text(encoding="utf-8"))
    assert "claimed_pid" not in job and "cuda_visible_devices" not in job
    assert alive.exists()


def test_retry_respects_max_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "QUEUE_ROOT", tmp_path)
    exhausted = move(enqueue(Q._job_args("TCGA-LAML"), ["TCGA-LAML"], ["0"], root=tmp_path)["created"][0],
                     "failed")
    job = json.loads(exhausted.read_text(encoding="utf-8"))
    job["retries"] = 3
    job["claimed_pid"] = 1
    exhausted.write_text(json.dumps(job) + "\n", encoding="utf-8")
    pending = move(enqueue(Q._job_args("TCGA-COAD"), ["TCGA-COAD"], ["0"], root=tmp_path)["created"][0],
                   "failed")

    retried = Q.cmd_retry(["TCGA-LAML", "TCGA-COAD"], max_retries=3)

    assert retried == 1
    assert Q.conf_exists("TCGA-LAML") == "failed"          # 次数用尽不再重试
    assert Q.conf_exists("TCGA-COAD") == "queue"
    requeued = json.loads((tmp_path / "queue" / pending.name).read_text(encoding="utf-8"))
    assert requeued["retries"] == 1 and "claimed_pid" not in requeued


def test_seed_occupied_reads_running_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "QUEUE_ROOT", tmp_path)
    _seed_running(tmp_path, "TCGA-LAML", claimed_pid=os.getpid(), gpu="3")
    _seed_running(tmp_path, "TCGA-COAD", claimed_pid=999_999_999, gpu="4")

    occupied = Q._seed_occupied(["TCGA-LAML", "TCGA-COAD"], {})

    assert occupied == {"TCGA-LAML": "3"}                  # 死 claim 不占槽；gpu 从 conf 复原
    assert Q._claimed_alive("TCGA-LAML") and not Q._claimed_alive("TCGA-COAD")
    # 已在 occupied 里的数据集不重复登记（watch 轮内幂等）
    assert Q._seed_occupied(["TCGA-LAML"], {"TCGA-LAML": "0"}) == {"TCGA-LAML": "0"}
