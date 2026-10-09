"""onehot 全局共享词表口径(2026-10-09 用户拍板):与 baseline/HGCN 共享词表对标。

全局词表 = 全部数据集患者合并后逐字段拟合;index k 跨数据集语义一致;
单数据集编码必须消费已落盘的共享词表(缺失即报错)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from discovery.onehot import (
    encode_onehot,
    fit_global_nominal_mappings,
    load_global_nominal_mapping,
    save_global_nominal_mapping,
)


def _patients(*ids):
    rows = []
    for pid, field, token in ids:
        rows.append({"patient_id": pid, "values": {field: [token]}})
    return rows


def test_global_mapping_union_and_rare_collapse():
    p1 = _patients(("a", "f1", "x"), ("b", "f1", "y"), ("c", "f1", "x"), ("a", "f2", "p"), ("b", "f2", "q"))
    p2 = _patients(("d", "f1", "x"), ("e", "f1", "z"), ("d", "f2", "p"))
    mapping = fit_global_nominal_mappings([p1, p2], ["f1", "f2"], rare_threshold=2)
    # x 跨数据集合计 3 次 >= 2 → 保留;y/z 各 1 次 → __OTHER__
    assert mapping["f1"] == {"__MISSING__": 0, "__OTHER__": 1, "x": 2}
    # p 跨数据集合计 2 次 >= 2 → 保留;q 1 次 → __OTHER__
    assert mapping["f2"] == {"__MISSING__": 0, "__OTHER__": 1, "p": 2}


def test_global_mapping_roundtrip_and_field_check(tmp_path: Path):
    mapping = fit_global_nominal_mappings(
        [_patients(("a", "f1", "x"))], ["f1"], rare_threshold=1
    )
    path = tmp_path / "onehot_global_mapping.json"
    save_global_nominal_mapping(path, mapping, landmark_tag="landmark_0", n_patients=1, n_datasets=1, rare_threshold=1)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["vocab_scope"] == "global_shared"
    assert load_global_nominal_mapping(path, fields=["f1"]) == mapping
    try:
        load_global_nominal_mapping(path, fields=["f1", "f_missing"])
    except ValueError as exc:
        assert "f_missing" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("缺字段应报错")


def test_encode_with_global_mapping_vocab_scope(tmp_path: Path):
    """编码时传 global_mapping:名义字段用共享词表,field_index 记 vocab_scope。"""
    torch = pytest.importorskip("torch")
    cases = [
        {"submitter_id": "a", "f1": "x"},
        {"submitter_id": "b", "f1": "rare_token"},
    ]
    cfg = {"fields": ["f1"], "converts": {}}
    mapping = {"f1": {"__MISSING__": 0, "__OTHER__": 1, "x": 2}}
    out = tmp_path / "bank"
    result = encode_onehot(
        "TCGA-X", cfg, cases, out, rare_threshold=1,
        landmark=False, global_mapping=mapping,
    )
    index = json.loads((out / "field_index.json").read_text(encoding="utf-8"))
    assert index["vocab_scope"] == "global_shared"
    # rare_token 不在共享词表 → __OTHER__(index 1);x → index 2
    import torch

    b = torch.load(out / "embeddings" / "pt" / "b.pt")
    assert int(b.argmax()) == 1
    a = torch.load(out / "embeddings" / "pt" / "a.pt")
    assert int(a.argmax()) == 2
    assert result["max_width"] == 3
