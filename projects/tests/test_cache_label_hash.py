"""缓存 label 哈希加固:schema v2、label_hash 入 key、v1 行不再命中。"""

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from selection.cache import SCHEMA_VERSION, SQLiteCache, make_cache_key
from selection.evaluator import Evaluator

N_FOLDS = 5


class _StubInner:
    def __init__(self, mean=0.7):
        self.mean, self.calls = mean, 0

    def evaluate(self, subset_idx):
        self.calls += 1
        return {"per_fold": [self.mean] * N_FOLDS, "c_index_mean": self.mean}


def _key_args(**overrides):
    args = dict(dataset="TCGA-GBM", landmark_tag="landmark_0", encoding="prompt",
                modality="mlp_clinic_flatten", seed=0, fields=("fa", "fb"),
                field_index_hash="fh", split_hashes=("s1", "s2"),
                train_args_hash="th", label_hash="lh")
    args.update(overrides)
    return args


def test_default_schema_is_v2_and_label_hash_changes_key():
    key = make_cache_key(**_key_args())
    other = make_cache_key(**_key_args(label_hash="other"))
    assert key != other
    missing = make_cache_key(**_key_args(label_hash="missing"))
    assert missing != key


def test_schema_version_bump_invalidates_v1_keys():
    key_v2 = make_cache_key(**_key_args())
    key_v1 = make_cache_key(**_key_args(), schema_version="e2-v1")
    assert key_v2 != key_v1
    assert SCHEMA_VERSION == "e2-v2"


def test_evaluator_cache_misses_when_label_hash_differs(tmp_path):
    cache_path = tmp_path / "cache.sqlite"
    fields = ("fa", "fb")
    first = Evaluator(_StubInner(), fields, seed=0, budget=10, cache=cache_path,
                      dataset="TCGA-GBM", landmark_tag="landmark_0",
                      field_index_hash="fh", split_hashes=("s1",), train_args_hash="th",
                      label_hash="label_a")
    first.evaluate(frozenset({"fa"}))
    # 同 label 哈希 → 命中缓存,不再物理训练
    second = Evaluator(_StubInner(), fields, seed=0, budget=10, cache=cache_path,
                       dataset="TCGA-GBM", landmark_tag="landmark_0",
                       field_index_hash="fh", split_hashes=("s1",), train_args_hash="th",
                       label_hash="label_a")
    result = second.evaluate(frozenset({"fa"}))
    assert result.physical_cache_hit is True
    assert second.physical_trains == 0
    # 不同 label 哈希 → miss,物理训练
    third = Evaluator(_StubInner(), fields, seed=0, budget=10, cache=cache_path,
                      dataset="TCGA-GBM", landmark_tag="landmark_0",
                      field_index_hash="fh", split_hashes=("s1",), train_args_hash="th",
                      label_hash="label_b")
    result = third.evaluate(frozenset({"fa"}))
    assert result.physical_cache_hit is False
    assert third.physical_trains == 1


def test_cache_payload_carries_schema_version(tmp_path):
    cache_path = tmp_path / "cache.sqlite"
    fields = ("fa",)
    evaluator = Evaluator(_StubInner(), fields, seed=0, budget=10, cache=cache_path,
                          dataset="TCGA-GBM", landmark_tag="landmark_0",
                          field_index_hash="fh", split_hashes=("s1",), train_args_hash="th",
                          label_hash="lh")
    evaluator.evaluate(frozenset({"fa"}))
    cache = SQLiteCache(cache_path)
    key = make_cache_key(dataset="TCGA-GBM", landmark_tag="landmark_0", encoding="prompt",
                         modality="mlp_clinic_flatten", seed=0, fields=("fa",),
                         field_index_hash="fh", split_hashes=("s1",), train_args_hash="th",
                         label_hash="lh")
    payload = cache.get(key)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert abs(payload["cv_c_mean"] - 0.7) < 1e-12


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in list(globals().items()):
            if name.startswith("test_"):
                fn(Path(tmp))
    print("ok")
