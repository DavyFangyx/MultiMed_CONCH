"""_run_uni_conf 的 worker namespace 回归测试(2026-10-13 秒挂根因)。

场景:旧批次 conf 的 args 快照里 conch_python/analyzer_python 等 worker 本地键
会被 merge_job_args 跳过(它们必须来自 drainer 的 parser 默认值)。空 Namespace
基座会 AttributeError——本测试锁定"带默认值的 parser namespace 做基座"这一契约。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import exp_queue as EQ  # noqa: E402


def test_run_uni_conf_merges_worker_defaults(tmp_path, monkeypatch):
    """真 conf(无 conch_python 等 worker 键)→ merge 后必须有 parser 默认值;conf args 生效。"""
    import greedy.univariate_cli as U

    # 1) 按真实 no_mask conf 的形态造假 conf(worker 本地键不进 args)
    queue = tmp_path / "q"
    (queue / "queue").mkdir(parents=True)
    conf = queue / "queue" / "fake__TCGA-BLCA__no_mask.conf"
    conf.write_text(json.dumps({
        "dataset": "TCGA-BLCA",
        "landmark_time": "none",
        "landmark_tag": "no_mask",
        "job_key": "fake",
        "args": {
            "dataset": "TCGA-BLCA",
            "landmark_time": "none",
            "extraction_mask": "off",
            "label_tag": "landmark_0",
            "field_bank_root": "/fake/outputs/_raw",
            "embeddings_root": "/fake/outputs/_raw",
            "results_dir": "/fake/results/single_raw",
            "encoding": "prompt",
            "analyzer": "mlp_clinic_flatten",
            "seed": 0,
            "max_epochs": 12,
        },
        "multi_dataset": False,
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    # 2) 捕获 run_one 收到的 merged namespace,不真训练
    captured: dict = {}
    def fake_run_one(args, dataset):
        captured["args"] = args
        captured["dataset"] = dataset
        return Path("/fake/out")

    monkeypatch.setattr(U, "run_one", fake_run_one)
    EQ._run_uni_conf(conf, field_workers=4)

    args = captured["args"]
    # worker 本地键:来自 parser 默认值(旧 bug 在这里 AttributeError)
    assert args.conch_python.endswith("conch/bin/python"), args.conch_python
    assert args.analyzer_python.endswith("SurvPGC/bin/python"), args.analyzer_python
    assert hasattr(args, "queue_root") and args.queue_root is None
    # device 不进当前 parser(无人读取),只要求 worker 本地键齐备
    # conf args 生效 + workers 覆盖
    assert args.field_bank_root == "/fake/outputs/_raw"
    assert args.extraction_mask == "off"
    assert args.analyzer == "mlp_clinic_flatten"
    assert args.workers == 4
    assert captured["dataset"] == "TCGA-BLCA"
    # conf 移进 done(经 mark_done)
    assert not conf.exists()
    assert (queue / "done" / conf.name).exists()


def test_run_uni_conf_marks_failed_on_error(tmp_path, monkeypatch):
    import greedy.univariate_cli as U

    queue = tmp_path / "q"
    (queue / "queue").mkdir(parents=True)
    conf = queue / "queue" / "fake__TCGA-BLCA__landmark_0.conf"
    conf.write_text(json.dumps({
        "dataset": "TCGA-BLCA",
        "landmark_time": "0",
        "landmark_tag": "landmark_0",
        "job_key": "fake",
        "args": {"dataset": "TCGA-BLCA", "landmark_time": "0",
                 "encoding": "prompt", "analyzer": "mlp_clinic_flatten", "seed": 0},
        "multi_dataset": False,
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    def boom(args, dataset):
        raise RuntimeError("boom")

    monkeypatch.setattr(U, "run_one", boom)
    EQ._run_uni_conf(conf, field_workers=4)
    assert (queue / "failed" / conf.name).exists()
    err = (queue / "failed" / conf.with_suffix(".err").name)
    assert err.exists() and "boom" in err.read_text(encoding="utf-8")
