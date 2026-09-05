"""Isolated A_manual pipeline: JSON -> L0-L5 prompt/CONCH embeddings and D0-D5 baseline vectors."""

from __future__ import annotations

import sys
from pathlib import Path

_A_PIPELINE_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _A_PIPELINE_ROOT.parent
_SRC = _PROJECT_ROOT / "src"
for _path in (_SRC, _PROJECT_ROOT):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.append(_path_str)
