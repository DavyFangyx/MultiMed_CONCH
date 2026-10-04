"""Test_3 / E2 A2_greedy：sig_stop(0.005, patience=3) 早停、历史 best 另报、产物落盘与缓存。

口径（spec §7.1 + 决策点 D4）：
  早停 = gain < 0.005 且 paired Wilcoxon(one-sided) p >= 0.05 连续 3 步；
  停在 k 步时 recommended = k - 3 步的前缀（k_sig），best = 全搜索历史最优（可更大）。
D4 修订（2026-10-04，用户确认）：新增 gain-only 模式（--stop-mode gain_only）——只按增益判定
（gain >= 0.005 更新 k_star 且清零，gain < 0.005 计数），不看 Wilcoxon；默认仍为 sig 以保持旧口径。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from selection.cache import SQLiteCache  # noqa: E402
from selection.evaluator import Evaluator  # noqa: E402
from selection.runner import SEARCHERS, run_one  # noqa: E402
from selection.search import GreedySearcher  # noqa: E402
from selection.stopping import SigStop, paired_wilcoxon_greater  # noqa: E402

# 让 {fa} 显著优于空集，之后每加一个字段只涨 ~0.0005 且 p=0.5 → 3 步后 sig_stop
STEP1 = (0.60, 0.62, 0.64, 0.66, 0.68)      # mean 0.64, p=0.03125 vs (0.5)*5
STEP2 = (0.6395, 0.6415, 0.6405, 0.6425, 0.6385)   # mean 0.6405, p=0.5
STEP3 = (0.6410, 0.6400, 0.6405, 0.6395, 0.6420)   # mean 0.6406, p=0.5
STEP4 = (0.6380, 0.6415, 0.6425, 0.6400, 0.6415)   # mean 0.6407, p=0.5


def test_d4_defaults_are_five_milli_and_three_patience():
    searcher = GreedySearcher()
    assert (searcher.delta, searcher.patience) == (0.005, 3)
    assert searcher.stop_mode == "sig"
    assert SEARCHERS["A2_greedy"] is GreedySearcher
    assert SEARCHERS["A2_greedy"]().delta == 0.005


def test_sigstop_needs_three_consecutive_no_improvement():
    stop = SigStop()
    flat = (0.5, 0.5, 0.5, 0.5, 0.5)
    assert stop.update(1, sum(STEP1) / 5, STEP1)["stopped"] is False
    assert stop.k_star == 1
    for k in (2, 3):
        state = stop.update(k, sum(STEP2) / 5, STEP2)
        assert state["stopped"] is False
    state = stop.update(4, sum(STEP2) / 5, STEP2)
    assert state["stopped"] is True and state["k_sig"] == 1
    # 空集基线：diffs 全 0 → p=1.0，gain=0 < 0.005 → 也算一次 no-improvement
    fresh = SigStop()
    assert paired_wilcoxon_greater(flat, flat)[0] == 1.0
    assert fresh.update(1, 0.5, flat)["stopped"] is False
    assert fresh.count == 1


def test_sigstop_resets_on_mixed_cases():
    # gain >= 0.005 但 p >= 0.05（涨幅不显著）→ 重置；gain < 0.005 但 p < 0.05（涨幅确定却太小）→ 也重置
    stop = SigStop()
    stop.update(1, sum(STEP1) / 5, STEP1)
    stop.update(2, sum(STEP2) / 5, STEP2)
    assert stop.count == 1
    tiny_significant = tuple(x + 0.001 for x in STEP1)  # diff 全 +0.001 → p=0.03125
    p, _ = paired_wilcoxon_greater(tiny_significant, STEP1)
    assert p < 0.05
    state = stop.update(3, sum(tiny_significant) / 5, tiny_significant)
    assert state["stopped"] is False and stop.count == 0


class _StubInner:
    """subset_idx -> 设计好的 (per_fold, mean)；未设计到的组合一律 0.5。"""

    def __init__(self, fields, table, default=(0.5,) * 5):
        self.fields = list(fields)
        self.table = table
        self.default = default
        self.calls = []

    def evaluate(self, subset_idx):
        names = tuple(sorted(self.fields[i] for i in subset_idx))
        self.calls.append(names)
        folds = self.table.get(frozenset(names), self.default)
        return {"per_fold": list(folds), "c_index_mean": sum(folds) / len(folds)}


def _evaluator(inner, fields, tmp_path, **kwargs):
    return Evaluator(inner, fields, seed=0, cache=None,
                     dataset="TCGA-TEST", landmark_tag="landmark_0", encoding="prompt",
                     modality="mlp_clinic_flatten", field_index_hash="h", split_hashes=("s",),
                     train_args_hash="t", jsonl_path=tmp_path / "evaluations.jsonl",
                     run_id="unit", algorithm="A2_greedy", **kwargs)


def test_greedy_sigstop_stops_early_and_reports_historical_best(tmp_path):
    fields = ("fa", "fb", "fc", "fd", "f5", "f6", "f7", "f8")
    inner = _StubInner(fields, {
        frozenset({"fa"}): STEP1,
        frozenset({"fa", "fb"}): STEP2,
        frozenset({"fa", "fb", "fc"}): STEP3,
        frozenset({"fa", "fb", "fc", "fd"}): STEP4,
    })
    evaluator = _evaluator(inner, fields, tmp_path)
    import numpy as np

    result = GreedySearcher().run(evaluator, fields, np.random.default_rng(0))

    assert result.stop_reason == "sig_stop"
    # recommended = 停在 k=4 时回退 3 步的前缀（k_sig=1）；best = 全搜索历史最优（k=4）
    assert tuple(result.recommended_subset) == ("fa",)
    assert tuple(result.best_subset) == ("fa", "fb", "fc", "fd")
    assert abs(result.best_cv_c_mean - sum(STEP4) / 5) < 1e-12
    # A2_greedy 属只读复用（spec §11），其 sig_stop 分支 metadata 只带 k_sig
    assert result.metadata["k_sig"] == 1
    assert [item["k"] for item in result.metadata["sig_stop_path"]] == [1, 2, 3, 4]
    # 早停发生在逻辑预算（8*9/2=36）之前：[8,7,6,5] 步候选
    assert result.logical_evals == 26 and result.logical_evals < 36
    assert result.physical_trains == 26
    # 每步只取 step 内 argmax（历史 best 覆盖所有候选）
    assert frozenset(inner.calls[0]) == frozenset({"fa"})


def test_run_one_lands_result_json_and_reuses_cache(tmp_path):
    fields = ("fa", "fb", "fc", "fd")
    inner = _StubInner(fields, {frozenset({"fa"}): STEP1})
    out = tmp_path / "run"
    cache = SQLiteCache(tmp_path / "cache.sqlite")
    args = dict(algo="A2_greedy", seed=0, fields=fields,
                field_index_hash="h", split_hashes=("s",), train_args_hash="t",
                dataset="TCGA-TEST", landmark_tag="landmark_0", modality="mlp_clinic_flatten",
                field_indices=(0, 1, 2, 3))
    run_one(inner=inner, output=out, cache=cache, **args)
    payload = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert payload["stop_reason"] == "sig_stop"
    assert payload["recommended_subset"] == ["fa"]
    assert abs(payload["recommended_cv_c_mean"] - 0.64) < 1e-12
    assert payload["recommended_k"] == 1 and payload["cache_hits"] == 0
    assert (out / "evaluations.jsonl").exists()

    # 第二遍：全命中缓存 → 不发生物理训练（E2 cache 语义）
    run_one(inner=inner, output=tmp_path / "run2", cache=cache, **args)
    payload2 = json.loads((tmp_path / "run2" / "result.json").read_text(encoding="utf-8"))
    assert payload2["cache_hits"] == payload2["logical_evals"] > 0
    assert payload2["physical_trains"] == 0


# --- gain_only（D4 修订 2026-10-04） -----------------------------------------

def test_sigstop_rejects_unknown_mode():
    with pytest.raises(ValueError):
        SigStop(mode="nope")


def test_sigstop_gain_only_updates_kstar_on_gain_ignoring_p():
    # gain >= 0.005 但 p >= 0.05（sig 模式的混合情形只清零）→ gain_only 必须更新 k_star
    stop = SigStop(mode="gain_only")
    stop.update(1, sum(STEP1) / 5, STEP1)
    assert stop.k_star == 1
    mixed = (0.705, 0.705, 0.62, 0.60, 0.60)  # mean 0.646，gain +0.006 >= 0.005；2 正 3 负 → p >= 0.05
    p, _ = paired_wilcoxon_greater(mixed, STEP1)
    assert p >= 0.05
    state = stop.update(2, sum(mixed) / 5, mixed)
    assert state["stopped"] is False
    assert stop.k_star == 2 and stop.count == 0


def test_sigstop_gain_only_counts_tiny_significant_gain():
    # gain < 0.005 但 p < 0.05（sig 模式的混合情形清零）→ gain_only 计数
    stop = SigStop(mode="gain_only")
    stop.update(1, sum(STEP1) / 5, STEP1)
    tiny = tuple(x + 0.001 for x in STEP1)  # gain 0.001 < 0.005，diff 全正 → p=0.03125
    p, _ = paired_wilcoxon_greater(tiny, STEP1)
    assert p < 0.05  # sig 模式下这里是 count=0
    assert stop.update(2, sum(tiny) / 5, tiny)["stopped"] is False
    assert stop.count == 1
    stop.update(3, sum(tiny) / 5, tiny)
    state = stop.update(4, sum(tiny) / 5, tiny)
    assert state["stopped"] is True and state["k_sig"] == 1


def test_greedy_gain_only_stops_and_reports(tmp_path):
    fields = ("fa", "fb", "fc", "fd", "f5", "f6", "f7", "f8")
    inner = _StubInner(fields, {
        frozenset({"fa"}): STEP1,
        frozenset({"fa", "fb"}): STEP2,
        frozenset({"fa", "fb", "fc"}): STEP3,
        frozenset({"fa", "fb", "fc", "fd"}): STEP4,
    })
    evaluator = _evaluator(inner, fields, tmp_path)
    import numpy as np

    result = GreedySearcher(stop_mode="gain_only").run(evaluator, fields, np.random.default_rng(0))

    assert result.stop_reason == "gain_stop"
    assert tuple(result.recommended_subset) == ("fa",)
    assert result.metadata["k_sig"] == 1
    assert result.metadata["stop_mode"] == "gain_only"
    assert [item["k"] for item in result.metadata["sig_stop_path"]] == [1, 2, 3, 4]
    assert result.logical_evals == 26


def test_run_one_gain_only_lands_stop_mode_in_result(tmp_path):
    fields = ("fa", "fb", "fc", "fd")
    inner = _StubInner(fields, {frozenset({"fa"}): STEP1})
    out = tmp_path / "run"
    cache = SQLiteCache(tmp_path / "cache.sqlite")
    args = dict(algo="A2_greedy", seed=0, fields=fields,
                field_index_hash="h", split_hashes=("s",), train_args_hash="t",
                dataset="TCGA-TEST", landmark_tag="landmark_0", modality="mlp_clinic_flatten",
                field_indices=(0, 1, 2, 3))
    run_one(inner=inner, output=out, cache=cache, stop_mode="gain_only", **args)
    payload = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert payload["stop_reason"] == "gain_stop"
    assert payload["stop_mode"] == "gain_only"
    assert payload["recommended_subset"] == ["fa"]
    assert payload["recommended_k"] == 1
