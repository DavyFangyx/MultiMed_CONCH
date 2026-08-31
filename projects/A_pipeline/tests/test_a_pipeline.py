from __future__ import annotations

import json
import sys
from pathlib import Path


A_PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(A_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(A_PIPELINE_ROOT))

from src.baseline import resolve_baseline_schemes  # noqa: E402
from src.config import load_custom_schemes, reset_scheme_registry, resolve_scheme_names  # noqa: E402
from src.datasets import dataset_jobs, load_dataset_configs, resolve_dataset_names  # noqa: E402
from src.json2prompt import run_json2prompt  # noqa: E402
from src.paths import (  # noqa: E402
    A_PIPELINE_ROOT,
    DEFAULT_DATASETS_CONFIG,
    DEFAULT_JSON_PATH,
    DEFAULT_TEMPLATE_DIR,
    dataset_baseline_embedding_dir,
    dataset_embedding_dir,
    dataset_prompt_dir,
    global_mapping_dir,
)


def test_scheme_loader_skips_field_bank():
    reset_scheme_registry()
    load_custom_schemes(DEFAULT_TEMPLATE_DIR)
    assert resolve_scheme_names("all") == ["L0", "L1", "L2", "L3", "L4", "L5"]
    try:
        resolve_scheme_names("FIELD_BANK")
        raise AssertionError("FIELD_BANK should be rejected")
    except ValueError as exc:
        assert "FIELD_BANK" in str(exc)


def test_default_datasets_are_lizhe_nine():
    assert DEFAULT_DATASETS_CONFIG.endswith("/A_pipeline/datasets.json")
    assert DEFAULT_JSON_PATH.startswith("/data/lizhe/")
    datasets = load_dataset_configs(DEFAULT_DATASETS_CONFIG)
    assert resolve_dataset_names("all", datasets) == [
        "TCGA-BRCA",
        "TCGA_LIHC",
        "TCGA-COAD",
        "TCGA-PRAD",
        "TCGA-READ",
        "TCGA-STAD",
        "TCGA-KICH",
        "TCGA-KIRC",
        "TCGA-KIRP",
    ]
    kidney_json = (
        "/data/lizhe/Medteam_projects/kindey_cancer_TCGA/clinical/clinical.cart.2026-03-17.json"
    )
    for name in ("TCGA-KICH", "TCGA-KIRC", "TCGA-KIRP"):
        assert datasets[name]["clinic_files"] == [kidney_json]
        assert datasets[name]["project_ids"] == [name]
    for cfg in datasets.values():
        assert all(path.startswith("/data/lizhe/") for path in cfg["clinic_files"])


def test_dataset_jobs_write_to_a_manual():
    jobs = dataset_jobs(
        "TCGA-READ",
        {"TCGA-READ": {"clinic_files": ["/tmp/read.json"], "project_ids": ["TCGA-READ"]}},
        json_path="unused.json",
        prompt_dir="/tmp/unused_prompt",
        out_dir="/tmp/unused_out",
        baseline_out="/tmp/outputs",
    )
    assert len(jobs) == 1
    assert jobs[0]["prompt_dir"] == dataset_prompt_dir("TCGA-READ")
    assert jobs[0]["out_dir"] == dataset_embedding_dir("TCGA-READ")
    assert jobs[0]["baseline_out_dir"] == dataset_baseline_embedding_dir("TCGA-READ", "/tmp/outputs")
    assert jobs[0]["prompt_dir"].endswith("/A_manual")
    assert "field_bank" not in jobs[0]["prompt_dir"]
    assert "greedy" not in jobs[0]["out_dir"]


def test_baseline_schemes_are_d0_d5():
    assert resolve_baseline_schemes("all") == ["D0", "D1", "D2", "D3", "D4", "D5"]
    assert resolve_baseline_schemes("D0") == ["D0"]


def test_global_mapping_dir_lives_in_a_pipeline():
    mapping_dir = global_mapping_dir()
    assert mapping_dir == A_PIPELINE_ROOT / "baseline_onehot_mapping_tables"
    assert mapping_dir.parent == A_PIPELINE_ROOT
    assert "outputs" not in mapping_dir.parts[-3:]


def test_json2prompt_writes_a_manual(tmp_path):
    json_path = tmp_path / "cases.json"
    json_path.write_text(
        json.dumps(
            [
                {
                    "submitter_id": "TCGA-XX-0001",
                    "demographic": {
                        "age_at_index": 60,
                        "gender": "male",
                        "race": "white",
                    },
                    "diagnoses": [
                        {
                            "diagnosis_is_primary_disease": "true",
                            "primary_diagnosis": "Adenocarcinoma",
                            "ajcc_pathologic_stage": "Stage I",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    prompt_dir = tmp_path / "outputs" / "TCGA-READ" / "A_manual"
    reset_scheme_registry()
    load_custom_schemes(DEFAULT_TEMPLATE_DIR)
    out = run_json2prompt(
        json_path=str(json_path),
        scheme="L0",
        template_dir=DEFAULT_TEMPLATE_DIR,
        prompt_dir=str(prompt_dir),
        dataset_name="TCGA-READ",
    )
    csv_path = Path(out)
    assert csv_path == prompt_dir / "L0" / "prompts.csv"
    text = csv_path.read_text(encoding="utf-8")
    assert "TCGA-XX-0001" in text
    assert "The patient is 60 years old at index." in text
    assert "Race is white." in text
