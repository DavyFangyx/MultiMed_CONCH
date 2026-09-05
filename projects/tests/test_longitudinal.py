from pathlib import Path
import json
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common.paths import PROJECT_ROOT, dataset_field_bank_dir
from discovery.field_bank import extract_field_bank_raw_values, generate_field_bank_prompt_row
from discovery.longitudinal import (
    DAYS_SINCE_FIELD,
    ECOG_CHANGE_FIELD,
    ECOG_FIELD,
    add_derived_fields_to_cfg,
    build_follow_up_records,
    collect_record_field_values,
    generate_record_prompt_row,
    run_longitudinal_dataset,
)


def _case():
    return {
        "submitter_id": "TCGA-XX-0001",
        "demographic": {"race": "white"},
        "follow_ups": [
            {
                "ecog_performance_status": "0",
                "days_to_follow_up": 30,
                "other_clinical_attributes": [{"bmi": 22.0, "weight": 60.0}],
            },
            {
                "ecog_performance_status": "1",
                "days_to_follow_up": 90,
                "other_clinical_attributes": [{"bmi": 24.0, "weight": 62.0}],
            },
            {
                "ecog_performance_status": "3",
                "days_to_follow_up": 200,
                "other_clinical_attributes": [{"bmi": 26.0, "weight": 64.0}],
            },
        ],
    }


def _cfg():
    fields = [ECOG_FIELD, "demographic.race"]
    return {
        "fields": fields,
        "output_cols": ["ecog", "race"],
        "templates": {
            ECOG_FIELD: "ECOG is {}.",
            "demographic.race": "Race is {}.",
        },
        "converts": {ECOG_FIELD: "", "demographic.race": ""},
    }


def test_build_follow_up_records_computes_days_and_changes():
    records = build_follow_up_records(_case(), landmark=True, landmark_time=100)
    assert [item["record_days"] for item in records] == [30.0, 90.0]
    assert records[0]["derived_values"][DAYS_SINCE_FIELD] is None
    assert records[1]["derived_values"][DAYS_SINCE_FIELD] == 60.0
    assert records[0]["derived_values"][ECOG_CHANGE_FIELD] is None
    assert records[1]["derived_values"][ECOG_CHANGE_FIELD] == 1.0


def test_placeholder_record_does_not_fall_back_to_whole_case():
    case = {
        "submitter_id": "TCGA-XX-0002",
        "demographic": {"race": "asian"},
        "follow_ups": [
            {
                "ecog_performance_status": "2",
                "days_to_follow_up": 40,
            }
        ],
    }
    records = build_follow_up_records(case, landmark=True, landmark_time=10)
    assert len(records) == 1
    assert records[0]["follow_up"] is None
    values = extract_field_bank_raw_values(
        case,
        ECOG_FIELD,
        landmark={
            "current_follow_up": None,
            "no_mask": True,
            "slots": {},
            "record": {},
            "last_time": None,
        },
    )
    assert values == []
    row = generate_record_prompt_row(
        case, _cfg(), records[0], use_landmark=True, landmark_time=10
    )
    assert row["_mask"]["ecog"] is False
    assert "not reported" in row["ecog"]
    assert row["_mask"]["race"] is True


def test_add_derived_fields_to_cfg_appends_once():
    cfg = add_derived_fields_to_cfg(_cfg())
    again = add_derived_fields_to_cfg(cfg)
    assert again["fields"].count(DAYS_SINCE_FIELD) == 1
    assert DAYS_SINCE_FIELD in again["fields"]
    assert ECOG_CHANGE_FIELD in again["fields"]


def test_dataset_field_bank_dir_longitudinal():
    path = dataset_field_bank_dir("TCGA-BRCA", "prompt", "landmark_365", experiment="longitudinal")
    assert path == PROJECT_ROOT / "outputs" / "TCGA-BRCA" / "longitudinal" / "field_bank" / "prompt" / "landmark_365"


def test_run_longitudinal_prompt_layout(tmp_path, monkeypatch):
    from discovery import longitudinal as module

    monkeypatch.setattr(module, "dataset_field_bank_dir", lambda *args, **kwargs: tmp_path / "out")
    args = type("Args", (), {"prompts_only": True, "rare_freq_threshold": 5})()
    result = run_longitudinal_dataset(
        dataset_name="TCGA-BRCA",
        cfg=_cfg(),
        cases=[_case()],
        args=args,
        encoding="prompt",
        use_landmark=True,
        landmark_time=100,
        tag="landmark_100",
    )
    index = json.loads((result["out_dir"] / "field_index.json").read_text())
    assert index["layout"] == "field_major_records"
    assert index["tokens_per_field"] == 2
    assert index["n_records"] == 2
    assert DAYS_SINCE_FIELD in index["fields"]
    prompts = (result["out_dir"] / "prompts.csv").read_text()
    assert "TCGA-XX-0001" in prompts


def test_run_longitudinal_onehot_shape(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    from discovery import longitudinal as module

    monkeypatch.setattr(module, "dataset_field_bank_dir", lambda *args, **kwargs: tmp_path / "out")
    args = type("Args", (), {"prompts_only": False, "rare_freq_threshold": 1})()
    result = run_longitudinal_dataset(
        dataset_name="TCGA-BRCA",
        cfg=_cfg(),
        cases=[_case()],
        args=args,
        encoding="onehot",
        use_landmark=True,
        landmark_time=100,
        tag="landmark_100",
    )
    matrix = torch.load(result["out_dir"] / "embeddings" / "pt" / "TCGA-XX-0001.pt", map_location="cpu")
    index = json.loads((result["out_dir"] / "field_index.json").read_text())
    assert tuple(matrix.shape) == (index["n_fields"] * index["n_records"], index["feat_dim"])
    assert index["layout"] == "field_major_records"


if __name__ == "__main__":
    pytest.main([__file__])
