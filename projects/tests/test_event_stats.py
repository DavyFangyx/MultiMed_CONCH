import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import run_event_stats
from time_stats import WRITE_KIND, _expand_kind_columns, _synthetic_cases, extract_patient_time_record


def _frames():
    records = [extract_patient_time_record(case, dataset_name="synthetic") for case in _synthetic_cases()]
    return pd.DataFrame(_expand_kind_columns(records, WRITE_KIND))


def _fake_tree(tmp_path):
    """建一棵假的 rawdata_stats:TCGA-AA(int event 列)、TCGA-BB(字符串 event 列)、TCGA-CC(无文件)。"""
    write_df = _frames()
    aa_dir = tmp_path / "TCGA-AA" / "time_write"
    aa_dir.mkdir(parents=True)
    write_df.to_csv(aa_dir / "patient_time_stats.csv", index=False)

    bb_dir = tmp_path / "TCGA-BB" / "time_write"
    bb_dir.mkdir(parents=True)
    str_df = pd.DataFrame(
        {
            "submitter_id": ["B1", "B2", "B3"],
            "event": ["1.0", "0.0", ""],
            "ground_truth_time": [100, 200, 300],
        }
    )
    str_df.to_csv(bb_dir / "patient_time_stats.csv", index=False)

    config = {
        "TCGA-AA": {},
        "TCGA-BB": {},
        "TCGA-CC": {},
    }
    config_path = tmp_path / "datasets.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def test_write_event_summary(tmp_path):
    write_df = _frames()
    path = run_event_stats.write_event_summary([("synthetic", write_df)], tmp_path)
    assert path is not None and path.exists()
    summary = pd.read_csv(path)
    assert summary.iloc[0].to_dict() == {
        "dataset": "synthetic",
        "n_patients": 2,
        "n_event": 1,
        "n_censored": 1,
        "n_unknown": 0,
        "event_rate": 0.5,
        "n_event_no_time": 0,
        "n_censored_no_time": 0,
    }


def test_write_event_summary_unknown_vital_and_missing_time(tmp_path):
    cases = _synthetic_cases()
    unknown = dict(cases[0])
    unknown["submitter_id"] = "TCGA-AA-0003"
    unknown["demographic"] = {"vital_status": "Not Reported"}
    dead_no_time = dict(cases[1])
    dead_no_time["submitter_id"] = "TCGA-AA-0004"
    dead_no_time["demographic"] = {"vital_status": "Dead", "days_to_death": None}
    records = [
        extract_patient_time_record(case, dataset_name="synthetic") for case in cases + [unknown, dead_no_time]
    ]
    write_df = pd.DataFrame(_expand_kind_columns(records, WRITE_KIND))
    path = run_event_stats.write_event_summary([("synthetic", write_df)], tmp_path)
    summary = pd.read_csv(path).iloc[0]
    assert summary["n_patients"] == 4
    assert summary["n_event"] == 2  # dead + dead_no_time(仍算事件,只是缺时间)
    assert summary["n_censored"] == 1
    assert summary["n_unknown"] == 1
    assert summary["n_event_no_time"] == 1
    assert summary["n_censored_no_time"] == 0
    assert summary["event_rate"] == round(2 / 3, 4)


def test_write_dataset_event_stats_normalizes_event(tmp_path):
    write_df = _frames()
    str_df = pd.DataFrame(
        {
            "submitter_id": ["B1", "B2", "B3"],
            "event": ["1.0", "0.0", ""],
            "ground_truth_time": [100, 200, 300],
        }
    )
    path = run_event_stats.write_dataset_event_stats(str_df, tmp_path)
    out = pd.read_csv(path)
    assert list(out["event"].iloc[:2]) == [1, 0]
    assert pd.isna(out["event"].iloc[2])
    assert list(out["submitter_id"]) == ["B1", "B2", "B3"]
    # 只保留事件相关的核心列,不带 slot 展开列
    assert "diagnoses_record1" not in out.columns
    assert set(run_event_stats.EVENT_COLUMNS) >= set(out.columns)


def test_main_writes_per_dataset_and_shared_summary(tmp_path, capsys):
    config_path = _fake_tree(tmp_path)
    run_event_stats.main(
        ["--dataset", "all", "--out_root", str(tmp_path), "--datasets_config", str(config_path)]
    )

    out = capsys.readouterr().out
    assert "TCGA-AA" in out and "TCGA-BB" in out
    assert "TCGA-CC" in out and "[跳过]" in out  # 没有 patient_time_stats.csv 的只提示跳过
    assert (tmp_path / "TCGA-AA" / "event_stats.csv").exists()
    assert (tmp_path / "TCGA-BB" / "event_stats.csv").exists()
    assert not (tmp_path / "TCGA-CC" / "event_stats.csv").exists()

    aa = pd.read_csv(tmp_path / "TCGA-AA" / "event_stats.csv")
    assert list(aa["event"]) == [0, 1]  # int 列归一后仍是 1/0

    summary = pd.read_csv(tmp_path / "_shared" / "event_summary.csv")
    assert list(summary["dataset"]) == ["TCGA-AA", "TCGA-BB"]
    assert list(summary["n_event"]) == [1, 1]
    assert list(summary["n_censored"]) == [1, 1]
    assert list(summary["n_unknown"]) == [0, 1]


def test_main_single_dataset_still_summarizes_all_on_disk(tmp_path, capsys):
    config_path = _fake_tree(tmp_path)
    run_event_stats.main(
        ["--dataset", "TCGA-AA", "--out_root", str(tmp_path), "--datasets_config", str(config_path)]
    )

    out = capsys.readouterr().out
    assert (tmp_path / "TCGA-AA" / "event_stats.csv").exists()
    assert not (tmp_path / "TCGA-BB" / "event_stats.csv").exists()  # 只写选中的数据集
    # 汇总表仍然覆盖磁盘上已有的全部数据集
    summary = pd.read_csv(tmp_path / "_shared" / "event_summary.csv")
    assert list(summary["dataset"]) == ["TCGA-AA", "TCGA-BB"]


def test_main_no_patient_time_stats(tmp_path, capsys):
    config_path = tmp_path / "datasets.json"
    config_path.write_text("{}", encoding="utf-8")
    run_event_stats.main(["--out_root", str(tmp_path), "--datasets_config", str(config_path)])
    out = capsys.readouterr().out
    assert not (tmp_path / "_shared").exists()
    assert "请先运行 scripts/run_time_stats.py" in out
