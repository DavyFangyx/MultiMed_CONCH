#!/usr/bin/env python3
"""CLI entry for the standalone PGC (SurvPGC) L0-L5 / D0-D5 line."""

import sys
from pathlib import Path


A_PIPELINE_PGC_ROOT = Path(__file__).resolve().parent

if str(A_PIPELINE_PGC_ROOT) not in sys.path:
    sys.path.insert(0, str(A_PIPELINE_PGC_ROOT))

from src.cli import main  # noqa: E402


if __name__ == "__main__":
    main()
