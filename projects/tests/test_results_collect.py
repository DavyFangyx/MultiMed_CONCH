from pathlib import Path
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "results_display" / "scripts"
for path in (SRC, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from common.paths import (
    PROJECT_ROOT,
    dataset_greedy_results_dir,
    dataset_linear_probe_results_dir,
    dataset_univariate_results_dir,
    display_results_dir,
)
from collect_common import collect_named_files, write_combined_csv
from collect_greedy_cindex import locate_dataset as locate_greedy
from collect_linear_probe_r2 import locate_dataset as locate_probe
from collect_univariate_cindex import locate_dataset as locate_univariate


def test_collectors_read_results_not_outputs():
    greedy = locate_greedy("TCGA-BRCA", "prompt", "landmark_0")["src_dir"]
    univariate = locate_univariate("TCGA_LIHC", "prompt", "landmark_365")["src_dir"]
    probe = locate_probe("TCGA_LIHC", "prompt", "landmark_730")["src_dir"]
    assert greedy == dataset_greedy_results_dir("TCGA-BRCA", "prompt", "landmark_0")
    assert univariate == dataset_univariate_results_dir("TCGA_LIHC", "prompt", "landmark_365")
    assert probe == dataset_linear_probe_results_dir("TCGA_LIHC", "prompt", "landmark_730")
    assert greedy.parts[-5:] == ("results", "greedy", "prompt", "landmark_0", "TCGA-BRCA")
    assert "outputs" not in greedy.as_posix()
    assert display_results_dir("univariate", "prompt", "landmark_none") == PROJECT_ROOT / "results_display" / "univariate" / "prompt" / "landmark_none"


def test_collect_named_files_and_combined_csv(tmp_path):
    src_a = tmp_path / "A"
    src_b = tmp_path / "B"
    src_a.mkdir()
    src_b.mkdir()
    (src_a / "field_cindex.csv").write_text("field,c_index_mean\nf0,0.6\n", encoding="utf-8")
    (src_b / "field_cindex.csv").write_text("field,c_index_mean\nf1,0.7\n", encoding="utf-8")

    def locate(name, encoding, landmark_tag):
        return {"src_dir": tmp_path / name}

    records, missing = collect_named_files(
        ["A", "B", "C"],
        encoding="prompt",
        landmark_tag="landmark_none",
        locate=locate,
        required=["field_cindex.csv"],
        csv_key="field_cindex.csv",
        csv_columns=["field", "c_index_mean"],
    )
    assert [row["dataset"] for row in records] == ["A", "B"]
    assert missing[0]["dataset"] == "C"
    out = tmp_path / "combined.csv"
    write_combined_csv(out, records, ["field", "c_index_mean"])
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [row["dataset"] for row in rows] == ["A", "B"]
    assert [row["field"] for row in rows] == ["f0", "f1"]


if __name__ == "__main__":
    import tempfile
    test_collectors_read_results_not_outputs()
    with tempfile.TemporaryDirectory() as tmp:
        test_collect_named_files_and_combined_csv(Path(tmp))
    print("ok")
