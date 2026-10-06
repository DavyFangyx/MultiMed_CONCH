"""独立 PGC (SurvPGC) 线：JSON -> L0-L5 prompt/CONCH embeddings + D0-D5 baseline。

基础库用的是本线自带的 A_pipeline_pgc/common 快照,不引 projects/src。
"""

from __future__ import annotations

import sys
from pathlib import Path

_PGC_ROOT = Path(__file__).resolve().parents[1]
for _path in (_PGC_ROOT,):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)
