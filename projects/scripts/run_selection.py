"""Compatibility entry point for the E2 selection runner."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from selection.runner import main


if __name__ == "__main__":
    main()
