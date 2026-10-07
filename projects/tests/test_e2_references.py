"""A0/A0b 参考线接入:SearchResult 形状 + seed_record 可消费。"""

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from selection.config import N_FOLDS
from selection.references import A0Full, A0bTopK
from selection.report import seed_record
from selection.runner import run_one
from selection.types import SearchResult


class _StubInner:
    """每次评估返回 key 决定好的固定分数;空集走 Evaluator 的 0.5 固定值不训练。"""

    def __init__(self, scores):
        self.scores = dict(scores)
        self.calls = []
        self.dataset = "TCGA-TEST"

    def evaluate(self, subset_idx):
        self.calls.append(tuple(sorted(subset_idx)))
        key = frozenset(int(i) for i in subset_idx)
        mean = self.scores.get(key, 0.5)
        return {"per_fold": [mean] * N_FOLDS, "c_index_mean": mean}


def _rows(fields, means):
    return [{"field": name, "field_idx": idx, "c_index_mean": mean}
            for idx, (name, mean) in enumerate(zip(fields, means))]


def test_a0_full_returns_search_result_with_full_subset(tmp_path):
    fields = ("fa", "fb", "fc")
    inner = _StubInner({frozenset({0, 1, 2}): 0.71})
    result = run_one(algo="A0_full", seed=0, fields=fields, inner=inner,
                     output=tmp_path / "run", budget=10,
                     field_index_hash="h", split_hashes=("s",), train_args_hash="t",
                     dataset="TCGA-TEST", landmark_tag="landmark_0",
                     field_indices=(0, 1, 2))
    assert isinstance(result, SearchResult)
    assert result.algorithm == "A0_full"
    assert frozenset(result.best_subset) == frozenset(fields)
    assert result.recommended_subset == result.best_subset
    assert abs(result.best_cv_c_mean - 0.71) < 1e-12
    assert result.stop_reason == "reference"
    payload = json.loads((tmp_path / "run" / "result.json").read_text(encoding="utf-8"))
    assert payload["algorithm"] == "A0_full"
    assert payload["recommended_k"] == 3


def test_a0b_topk_recommends_best_k_subset_and_writes_k_path(tmp_path):
    fields = ("fa", "fb", "fc", "fd")
    # 单字段先验:fa 最强;top-1 子集 0.68,top-3 子集 0.64 → 最优 k=1
    inner = _StubInner({frozenset({0}): 0.68, frozenset({1}): 0.55,
                        frozenset({2}): 0.54, frozenset({3}): 0.53,
                        frozenset({0, 1, 2}): 0.64, frozenset({0, 1, 2, 3}): 0.61})
    rows = _rows(fields, [0.68, 0.55, 0.54, 0.53])
    result = run_one(algo="A0b_topk", seed=0, fields=fields, inner=inner,
                     output=tmp_path / "run", budget=10,
                     univariate_rows=rows,
                     field_index_hash="h", split_hashes=("s",), train_args_hash="t",
                     dataset="TCGA-TEST", landmark_tag="landmark_0",
                     field_indices=(0, 1, 2, 3))
    assert result.algorithm == "A0b_topk"
    assert result.best_subset == ("fa",)
    assert result.recommended_subset == ("fa",)
    assert result.metadata["best_k"] == 1
    assert [item["k"] for item in result.metadata["k_path"]] == [1, 3, 4]


def test_reference_result_json_consumable_by_seed_record(tmp_path):
    fields = ("fa", "fb", "fc")
    inner = _StubInner({frozenset({0, 1, 2}): 0.71})
    out = tmp_path / "run"
    run_one(algo="A0_full", seed=0, fields=fields, inner=inner, output=out, budget=10,
            field_index_hash="h", split_hashes=("s",), train_args_hash="t",
            dataset="TCGA-TEST", landmark_tag="landmark_0", field_indices=(0, 1, 2))
    (out / "run_config.json").write_text(json.dumps({
        "dataset": "TCGA-TEST", "landmark_tag": "landmark_0",
        "modality": "mlp_clinic_flatten", "seed": 0, "fields": list(fields),
        "restricted_anchor": False,
    }), encoding="utf-8")
    record = seed_record(out)
    assert record["algorithm"] == "A0_full"
    assert abs(record["cv_c_mean"] - 0.71) < 1e-12
    assert record["recommended_k"] == 3


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in list(globals().items()):
            if name.startswith("test_"):
                fn(Path(tmp))
    print("ok")
