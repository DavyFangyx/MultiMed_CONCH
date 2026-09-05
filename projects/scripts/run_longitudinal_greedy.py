import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
SRC = PROJECT_ROOT / "src"

for path in (REPO_ROOT, SRC):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from greedy.cli import main as _main


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--experiment" not in argv:
        argv = ["--experiment", "longitudinal", *argv]
    _main(argv)


if __name__ == "__main__":
    main()
