"""内容指纹: skip 守卫的产物新鲜度判据(2026-10-09 用户拍板)。

字段模板 / 词表 / 字段集改动后,守卫必须能识别"旧产物已陈旧"并自动重建,
而不是仅凭产物存在或 n_patients 相等就静默复用(改模板不重编码 = 两臂输入
不再同源的隐患)。指纹一律 sha256 前 16 位十六进制,存进产物 index json。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def file_sha256(path: Path | str) -> str | None:
    path = Path(path)
    if not path.is_file():
        return None
    return content_sha256(path.read_text(encoding="utf-8"))


def payload_fingerprint(payload: dict | list) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return content_sha256(text)


def fields_fingerprint(fields: list[str]) -> str:
    return content_sha256(",".join(str(f) for f in fields))
