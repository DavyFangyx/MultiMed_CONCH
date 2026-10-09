"""内容指纹助手测试(2026-10-09 skip 守卫指纹化口径)。"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common.fingerprint import (
    content_sha256,
    fields_fingerprint,
    file_sha256,
    payload_fingerprint,
)


def test_content_sha256_deterministic_and_sensitive():
    assert content_sha256("abc") == content_sha256("abc")
    assert content_sha256("abc") != content_sha256("abd")
    assert len(content_sha256("abc")) == 16


def test_payload_fingerprint_key_order_invariant():
    assert payload_fingerprint({"a": 1, "b": [2, 3]}) == payload_fingerprint({"b": [2, 3], "a": 1})
    assert payload_fingerprint({"a": 1}) != payload_fingerprint({"a": 2})


def test_fields_fingerprint_order_sensitive():
    assert fields_fingerprint(["a", "b"]) != fields_fingerprint(["b", "a"])
    assert fields_fingerprint(["a", "b"]) == fields_fingerprint(["a", "b"])


def test_file_sha256(tmp_path: Path):
    f = tmp_path / "template.csv"
    f.write_text("field,template\n", encoding="utf-8")
    fp = file_sha256(f)
    assert fp is not None and len(fp) == 16
    f.write_text("field,template\nx,y\n", encoding="utf-8")
    assert file_sha256(f) != fp  # 模板改动 → 指纹变化 → 守卫判 stale
    assert file_sha256(tmp_path / "missing.csv") is None
