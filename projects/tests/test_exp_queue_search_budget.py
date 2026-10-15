"""Test_6 预算 cap 可配置与产物指纹的回归测试(2026-10-14)。

cap 进 --out 路径(cap_{cap} 一级目录)做产物指纹:
  1. enqueue --budget_cap 可覆盖,默认 500;
  2. 不同 cap → 不同 job_key 且不同产物目录(互不覆盖);
  3. report 零参数:argv 不含 --budget_cap,bakeoff 从目录名自动识别 cap;
  4. 试点网格仍是 3 数据集 × 8 算法 = 24。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import exp_queue as EQ  # noqa: E402
import run_bakeoff_report as BR  # noqa: E402

ARM = EQ.ARM_REGISTRY["test_6_search"]


def _flag_value(argv, flag):
    i = argv.index(flag)
    return argv[i + 1]


def test_t6_argv_default_cap_500_in_out():
    argv = EQ.t6_search_argv("TCGA-GBM", "A1_random")
    assert _flag_value(argv, "--budget_cap") == "500"
    assert "cap_500" in _flag_value(argv, "--out")


def test_t6_argv_custom_cap_in_out():
    argv = EQ.t6_search_argv("TCGA-GBM", "A1_random", budget_cap=300)
    assert _flag_value(argv, "--budget_cap") == "300"
    assert "cap_300" in _flag_value(argv, "--out")


def test_distinct_caps_give_distinct_job_keys():
    _, key500, _ = EQ.search_job(ARM, "TCGA-GBM", ("A1_random",), None, 500)
    _, key300, _ = EQ.search_job(ARM, "TCGA-GBM", ("A1_random",), None, 300)
    assert key500 != key300


def test_report_argv_needs_no_cap_flag(monkeypatch):
    captured = []

    def fake_call(argv, **kwargs):
        captured.extend(argv)
        return 0

    monkeypatch.setattr(EQ.subprocess, "call", fake_call)
    rc = EQ.cmd_search_report(ARM, argparse.Namespace())
    assert rc == 0
    assert "--budget_cap" not in captured
    assert _flag_value(captured, "--results-root") == "results/Test_6_search/prompt"


def test_t6_grid_is_24():
    assert len(EQ.search_units(ARM)) == 24


def test_discover_caps_explicit_cap_dir(tmp_path):
    cap_dir = tmp_path / "cap_300"
    cap_dir.mkdir()
    assert BR._discover_caps(cap_dir) == [(300, cap_dir)]


def test_discover_caps_multi_from_parent(tmp_path):
    (tmp_path / "landmark_0" / "cap_300").mkdir(parents=True)
    (tmp_path / "landmark_0" / "cap_500").mkdir(parents=True)
    (tmp_path / "junk_dir").mkdir()
    units = BR._discover_caps(tmp_path)
    assert [cap for cap, _ in units] == [300, 500]


def test_discover_caps_flat_legacy_layout(tmp_path):
    (tmp_path / "TCGA-GBM" / "A1_random").mkdir(parents=True)
    assert BR._discover_caps(tmp_path) == [(None, tmp_path)]
