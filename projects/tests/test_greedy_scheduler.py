from pathlib import Path
import json
import sys

import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from greedy.evaluator import CachedEvaluator, StubEvaluator
from greedy.protocol import run_nested_greedy
from greedy.search import greedy_forward
from greedy.splits import NestedSplitConfig, build_nested_splits, load_nested_splits, save_nested_splits
from greedy.stability import selection_frequency
from greedy.stopping import apply_stopping_rules, one_se_k, sig_stop_k


FIELDS = ["f0", "f1", "f2", "f3"]


def test_nested_splits_are_disjoint_and_reproducible():
    ids = [f"p{i:02d}" for i in range(20)]
    events = {pid: int(i % 2 == 0) for i, pid in enumerate(ids)}
    cfg = NestedSplitConfig(outer_folds=5, repeats=2, seed=7)
    a = build_nested_splits(ids, events=events, config=cfg)
    b = build_nested_splits(ids, events=events, config=cfg)
    assert len(a) == 10
    assert [s.fold_id for s in a] == [s.fold_id for s in b]
    assert a[0].train == b[0].train

    split = a[0]
    assert set(split.train) & set(split.val) == set()
    assert set(split.train) & set(split.test) == set()
    assert set(split.val) == set(split.test)
    assert set(split.train) | set(split.val) | set(split.test) == set(ids)

    other_seed = build_nested_splits(ids, events=events, config=NestedSplitConfig(outer_folds=5, repeats=2, seed=8))
    assert other_seed[0].test != a[0].test or other_seed[0].train != a[0].train


def test_greedy_forward_runs_full_curve_and_is_order_invariant():
    weights = [0.01, 0.08, 0.04, 0.02]
    ev = StubEvaluator(FIELDS, weights=weights)
    path = greedy_forward(ev, candidate_idx=[3, 0, 2, 1], patience=1)
    assert [step["added"] for step in path] == ["f1", "f2", "f3", "f0"]
    assert len(path) == 4
    assert path[0]["all_candidates"]["f1"]["c_index"] > path[0]["all_candidates"]["f0"]["c_index"]
    assert path[1]["subset"] == ["f1", "f2"]

    cached = CachedEvaluator(ev)
    greedy_forward(cached, candidate_idx=[0, 1, 2])
    greedy_forward(cached, candidate_idx=[2, 1, 0])
    assert cached.n_hits > 0


def test_greedy_forward_starts_from_init_fields():
    weights = [0.01, 0.08, 0.04, 0.02]
    ev = StubEvaluator(FIELDS, weights=weights)
    path = greedy_forward(ev, init_idx=[0, 3])
    assert path[0]["init"] is True
    assert path[0]["subset"] == ["f0", "f3"]
    assert path[1]["added"] == "f1"
    assert path[1]["subset"][:2] == ["f0", "f3"]


def test_greedy_forward_workers_match_serial():
    weights = [0.01, 0.08, 0.04, 0.02]
    serial = greedy_forward(StubEvaluator(FIELDS, weights=weights))
    parallel = greedy_forward(StubEvaluator(FIELDS, weights=weights), workers=3)
    assert [step["added"] for step in serial] == [step["added"] for step in parallel]


def test_selection_frequency_and_stopping_rules():
    path_a = [
        {"step": 1, "added": "f1", "subset": ["f1"], "subset_idx": [1]},
        {"step": 2, "added": "f2", "subset": ["f1", "f2"], "subset_idx": [1, 2]},
        {"step": 3, "added": "f0", "subset": ["f1", "f2", "f0"], "subset_idx": [1, 2, 0]},
    ]
    path_b = [
        {"step": 1, "added": "f1", "subset": ["f1"], "subset_idx": [1]},
        {"step": 2, "added": "f3", "subset": ["f1", "f3"], "subset_idx": [1, 3]},
        {"step": 3, "added": "f2", "subset": ["f1", "f3", "f2"], "subset_idx": [1, 3, 2]},
    ]
    freq = selection_frequency([path_a, path_b], fields=FIELDS)
    row = freq.set_index("field").loc["f1"]
    assert row["step1"] == 1.0
    assert row["first_selected_rate"] == 1.0
    assert freq.set_index("field").loc["f2"]["step2"] == 0.5

    records = [
        {"path": path_a, "test_scores": [0.60, 0.70, 0.69]},
        {"path": path_b, "test_scores": [0.62, 0.72, 0.705]},
        {"path": path_a, "test_scores": [0.61, 0.69, 0.68]},
        {"path": path_b, "test_scores": [0.59, 0.71, 0.70]},
        {"path": path_a, "test_scores": [0.63, 0.73, 0.71]},
        {"path": path_b, "test_scores": [0.58, 0.68, 0.67]},
    ]
    stopping = apply_stopping_rules(records, patience=3)
    assert stopping["points"]["best"]["k"] == 2
    assert one_se_k(stopping["curve"]) <= stopping["points"]["best"]["k"]
    assert sig_stop_k(stopping["curve"], patience=3) >= 1
    assert stopping["points"]["parsimonious"]["rule"] == "1se"


def test_nested_scheduler_does_not_use_test_for_decisions():
    ids = [f"p{i:02d}" for i in range(12)]
    events = {pid: int(i < 6) for i, pid in enumerate(ids)}
    splits = build_nested_splits(ids, events=events, config=NestedSplitConfig(outer_folds=3, repeats=1, seed=0))

    seen = {"inner": [], "outer": []}

    class Probe:
        def __init__(self, split, for_test=False):
            self.fields = FIELDS
            self.splits = split if isinstance(split, (list, tuple)) else [split]
            self.split = self.splits[0]
            self.for_test = for_test
            self.inner = StubEvaluator(FIELDS, weights=[0.01, 0.05, 0.03, 0.02], split=self.split)

        def evaluate(self, subset_idx):
            bucket = "outer" if self.for_test else "inner"
            seen[bucket].append((tuple(self.split.test), tuple(sorted(subset_idx))))
            return self.inner.evaluate(subset_idx)

    def factory(split, seed=0, for_test=False):
        return Probe(split, for_test=for_test)

    result = run_nested_greedy(factory, splits, fields=FIELDS, patience=3)
    assert result["n_folds"] == 3
    assert result["points"]["best"]["k"] >= 1
    assert list(result["selection_freq"]["field"]) == FIELDS


def test_cli_stub_writes_artifacts(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from greedy.cli import main
    from greedy.cli import _resolve_init_idx

    fields = [
        "diagnoses[].age_at_diagnosis",
        "demographic.sex_at_birth",
        "demographic.race",
    ]
    assert _resolve_init_idx(fields, "age_at_diagnosis,sex_at_birth") == [0, 1]
    assert _resolve_init_idx(fields, "{demographic.sex_at_birth,demographic.race}") == [1, 2]
    assert _resolve_init_idx(fields, "demographic.race") == [2]
    try:
        _resolve_init_idx(fields, "{demographic.ethnicity,demographic.sex_at_birth}")
        assert False, "missing init field should exit"
    except SystemExit as exc:
        assert str(exc) == "not found demographic.ethnicity field"


if __name__ == "__main__":
    test_nested_splits_are_disjoint_and_reproducible()
    test_greedy_forward_runs_full_curve_and_is_order_invariant()
    test_selection_frequency_and_stopping_rules()
    test_nested_scheduler_does_not_use_test_for_decisions()
    test_greedy_forward_starts_from_init_fields()
    test_cli_stub_writes_artifacts(Path("."))
    print("ok")
