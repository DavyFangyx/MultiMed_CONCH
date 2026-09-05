from pathlib import Path
import csv
import json
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common.paths import PROJECT_ROOT, dataset_linear_probe_dir
from discovery.linear_probe import (
    collect_continuous_targets,
    is_numeric_gdc_type,
    main,
    make_parser,
    require_prompt_encoding,
    run_one,
)


def _write_prompt_bank(bank: Path, fields: list[str], embeddings: dict[str, np.ndarray]) -> None:
    pt_dir = bank / "embeddings" / "pt"
    pt_dir.mkdir(parents=True, exist_ok=True)
    (bank / "field_index.json").write_text(
        json.dumps({"encoding": "prompt", "fields": fields, "n_fields": len(fields)}, indent=2) + "\n"
    )
    torch = pytest.importorskip("torch")
    for pid, matrix in embeddings.items():
        payload = {
            "matrix": torch.from_numpy(np.asarray(matrix, dtype=np.float32)),
            "mask": torch.ones(len(fields), dtype=torch.bool),
            "patient_id": pid,
        }
        torch.save(payload, pt_dir / f"{pid}.pt")


def test_dataset_linear_probe_dir_prompt():
    path = dataset_linear_probe_dir("TCGA_LIHC", "prompt", "landmark_none")
    assert path == PROJECT_ROOT / "outputs" / "TCGA_LIHC" / "linear_probe" / "prompt" / "landmark_none"
    assert path.as_posix().endswith("outputs/TCGA_LIHC/linear_probe/prompt/landmark_none")


def test_encoding_onehot_raises():
    with pytest.raises(ValueError, match="onehot"):
        require_prompt_encoding("onehot")
    parser = make_parser()
    args = parser.parse_args(["--dataset", "TCGA_LIHC", "--encoding", "onehot", "--landmark_time", "none"])
    with pytest.raises(ValueError, match="onehot"):
        require_prompt_encoding(args.encoding)
    with pytest.raises(ValueError, match="onehot"):
        main(["--dataset", "TCGA_LIHC", "--encoding", "onehot", "--landmark_time", "none"])


def test_nominal_fields_are_excluded():
    cases = [
        {
            "submitter_id": "TCGA-XX-0001",
            "demographic": {"sex_at_birth": "female", "age_at_index": 61},
        },
        {
            "submitter_id": "TCGA-XX-0002",
            "demographic": {"sex_at_birth": "male", "age_at_index": 54},
        },
    ]
    fields = ["demographic.sex_at_birth", "demographic.age_at_index"]
    dictionary = {
        ("demographic", "sex_at_birth"): "enum",
        ("demographic", "age_at_index"): "integer|null",
    }
    field_types, targets = collect_continuous_targets(
        cases,
        fields,
        landmark=False,
        landmark_policy="off",
        dictionary=dictionary,
    )
    assert [row["field"] for row in field_types if row["final_type"] == "continuous"] == [
        "demographic.age_at_index"
    ]
    assert "demographic.sex_at_birth" not in targets
    assert set(targets["demographic.age_at_index"]) == {"TCGA-XX-0001", "TCGA-XX-0002"}
    assert is_numeric_gdc_type("number")
    assert is_numeric_gdc_type("integer|null")
    assert not is_numeric_gdc_type("enum")


def test_absent_numeric_fields_are_omitted():
    cases = [
        {
            "submitter_id": "TCGA-XX-0001",
            "demographic": {"age_at_index": 61},
        },
        {
            "submitter_id": "TCGA-XX-0002",
            "demographic": {"age_at_index": 54},
        },
    ]
    fields = [
        "demographic.age_at_index",
        "follow_ups[].other_clinical_attributes[].bmi",
        "follow_ups[].other_clinical_attributes[].weight",
    ]
    dictionary = {
        ("demographic", "age_at_index"): "integer|null",
        ("other_clinical_attribute", "bmi"): "number",
        ("other_clinical_attribute", "weight"): "number",
    }
    field_types, targets = collect_continuous_targets(
        cases,
        fields,
        landmark=False,
        landmark_policy="off",
        dictionary=dictionary,
    )
    assert [row["field"] for row in field_types if row["final_type"] == "continuous"] == fields
    assert set(targets) == {"demographic.age_at_index"}
    assert "follow_ups[].other_clinical_attributes[].bmi" not in targets
    assert "follow_ups[].other_clinical_attributes[].weight" not in targets


def test_toy_recoverable_and_noise_and_skipped(tmp_path):
    fields = [
        "demographic.age_at_index",
        "follow_ups[].other_clinical_attributes[].bmi",
        "follow_ups[].other_clinical_attributes[].weight",
        "demographic.sex_at_birth",
    ]
    n_patients = 20
    patient_ids = [f"TCGA-XX-{i:04d}" for i in range(n_patients)]
    ages = {pid: float(40 + i) for i, pid in enumerate(patient_ids)}
    noise = {pid: float((i * 7) % 13) for i, pid in enumerate(patient_ids)}
    sparse = {pid: float(i) for i, pid in enumerate(patient_ids) if i < 5}

    embeddings = {}
    for i, pid in enumerate(patient_ids):
        matrix = np.zeros((len(fields), 8), dtype=np.float32)
        matrix[0, 0] = ages[pid]
        embeddings[pid] = matrix

    bank = tmp_path / "field_bank" / "prompt"
    _write_prompt_bank(bank, fields, embeddings)
    out_dir = tmp_path / "linear_probe"

    cases = []
    for i, pid in enumerate(patient_ids):
        cases.append(
            {
                "submitter_id": pid,
                "demographic": {
                    "age_at_index": ages[pid],
                    "sex_at_birth": "female" if i % 2 == 0 else "male",
                },
                "follow_ups": [
                    {
                        "other_clinical_attributes": [
                            {
                                "bmi": noise[pid],
                                "weight": sparse[pid] if pid in sparse else None,
                            }
                        ]
                    }
                ],
            }
        )

    dictionary = {
        ("demographic", "age_at_index"): "integer|null",
        ("other_clinical_attribute", "bmi"): "number",
        ("other_clinical_attribute", "weight"): "number",
        ("demographic", "sex_at_birth"): "enum",
    }
    parser = make_parser()
    args = parser.parse_args(
        [
            "--dataset",
            "TCGA_LIHC",
            "--field_bank_dir",
            str(bank),
            "--out",
            str(out_dir),
            "--min_valid",
            "10",
            "--seed",
            "0",
            "--landmark_time",
            "none",
        ]
    )
    run_one(args, "TCGA_LIHC", cases=cases, dictionary=dictionary)

    rows = list(csv.DictReader((out_dir / "numeric_r2.csv").open()))
    fields_in_csv = [row["field"] for row in rows]
    assert "demographic.sex_at_birth" not in fields_in_csv
    by_field = {row["field"]: row for row in rows}
    assert float(by_field["demographic.age_at_index"]["r2"]) > 0.95
    assert by_field["demographic.age_at_index"]["status"] == "ok"
    assert float(by_field["follow_ups[].other_clinical_attributes[].bmi"]["r2"]) < 0.2
    assert by_field["follow_ups[].other_clinical_attributes[].weight"]["status"] == "skipped"
    assert int(by_field["follow_ups[].other_clinical_attributes[].weight"]["n_valid"]) < 10
    assert rows[0]["field"] == "demographic.age_at_index"

    preds = list(csv.DictReader((out_dir / "predictions.csv").open()))
    assert preds
    assert {row["field"] for row in preds} <= {
        "demographic.age_at_index",
        "follow_ups[].other_clinical_attributes[].bmi",
    }
    config = json.loads((out_dir / "run_config.json").read_text())
    assert config["encoding"] == "prompt"
    assert config["model"] == "ridge"
    assert config["target"] == "onehot_aggregate_continuous_unscaled"
    assert config["n_continuous_fields"] == 3
    assert config["n_ok"] == 2
    assert config["n_skipped"] == 1
    assert config["landmark"] is False
