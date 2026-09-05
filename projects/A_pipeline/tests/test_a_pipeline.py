from __future__ import annotations

import json
import sys
from pathlib import Path


A_PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(A_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(A_PIPELINE_ROOT))

from src.baseline import (  # noqa: E402
    BASELINE_CONTINUOUS_FIELDS,
    BASELINE_DICTIONARY_FIELD_TYPES,
    BASELINE_NOMINAL_FIELDS,
    BASELINE_ONEHOT_FIELDS,
    BASELINE_ORDINAL_FIELDS,
    BASELINE_ORDINARY_FIELDS,
    BASELINE_SCHEME_FIELDS,
    PAPER_BASELINE_SCHEMES,
    _build_baseline_vector,
    _encode_ordinal_value,
    baseline_field_encoding,
    baseline_scheme_output_dir,
    fit_nominal_mappings,
    fit_onehot_mappings,
    load_baseline_scheme_fields,
    resolve_baseline_schemes,
)
from src.cli import main as a_pipeline_main  # noqa: E402
from src.config import DEFAULT_TEXT_SCHEMES, SCHEME_DATASETS, SCHEME_FIELDS, SCHEME_TEMPLATE, load_custom_schemes, reset_scheme_registry, resolve_scheme_names, schemes_for_dataset  # noqa: E402
from src.datasets import dataset_jobs, load_dataset_configs, resolve_dataset_names  # noqa: E402
from src.extract import extract_values  # noqa: E402
from src.hgcn_clinic import field_type_name, load_hgcn_scheme_fields, resolve_hgcn_schemes  # noqa: E402
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
from common.fields import HUMAN_SCHEME_FIELDS, L5_FIELDS, PAPER_FIELDS  # noqa: E402


def _load_scheme_fields():
    reset_scheme_registry()
    load_custom_schemes(DEFAULT_TEMPLATE_DIR)
    load_baseline_scheme_fields(SCHEME_FIELDS)
    load_hgcn_scheme_fields(SCHEME_FIELDS)


def test_scheme_dirs_load_fields_and_templates():
    _load_scheme_fields()
    paper = ["MULTISURV", "SURVPGC", "MMSURV", "INTEGRATIVE_DNN", "HGCN_KIRC", "HGCN_LIHC", "HGCN_ESCA", "HGCN_LUSC", "HGCN_LUAD", "HGCN_UCEC"]
    for name in DEFAULT_TEXT_SCHEMES + paper:
        assert name in SCHEME_FIELDS
        assert SCHEME_TEMPLATE[name] == f"{name}/template.csv"
        scheme_dir = Path(DEFAULT_TEMPLATE_DIR) / name
        assert (scheme_dir / "fields.json").exists()
        assert (scheme_dir / "template.csv").exists()
        assert SCHEME_FIELDS[name]


def test_scheme_dataset_bindings():
    _load_scheme_fields()
    assert SCHEME_DATASETS["L0"] is None
    assert SCHEME_DATASETS["HGCN_KIRC"] == ["TCGA-KIRC"]
    assert SCHEME_DATASETS["HGCN_LIHC"] == ["TCGA_LIHC"]
    assert "TCGA-BRCA" in SCHEME_DATASETS["MMSURV"]
    assert "TCGA-ESCA" in SCHEME_DATASETS["MMSURV"]
    assert "TCGA-READ" in SCHEME_DATASETS["SURVPGC"]
    assert "TCGA-BRCA" in SCHEME_DATASETS["MULTISURV"]
    assert len(SCHEME_DATASETS["MULTISURV"]) == 33
    assert len(SCHEME_DATASETS["INTEGRATIVE_DNN"]) == 33
    datasets = {"TCGA-KIRC": {}, "TCGA-READ": {}, "TCGA_LIHC": {}}
    assert schemes_for_dataset(["L0", "HGCN_KIRC", "MMSURV"], "TCGA-KIRC", datasets) == ["L0", "HGCN_KIRC"]
    assert schemes_for_dataset(["L0", "HGCN_KIRC", "MMSURV"], "TCGA-READ", datasets) == ["L0"]
    assert schemes_for_dataset(["D0", "HGCN_KIRC"], "TCGA-KIRC", datasets) == ["D0", "HGCN_KIRC"]
    assert schemes_for_dataset(["D0", "HGCN_KIRC"], "TCGA-READ", datasets) == ["D0"]
    assert schemes_for_dataset(["HGCN_LIHC"], "TCGA-LIHC", datasets) == ["HGCN_LIHC"]
    assert schemes_for_dataset(["HGCN_KIRC"], None, datasets) == ["HGCN_KIRC"]


def test_scheme_loader_skips_field_bank():
    _load_scheme_fields()
    assert resolve_scheme_names("all") == ["L0", "L1", "L2", "L3", "L4", "L5"]
    assert resolve_scheme_names("MULTISURV") == ["MULTISURV"]
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
    _load_scheme_fields()
    assert resolve_baseline_schemes("all") == ["D0", "D1", "D2", "D3", "D4", "D5"]
    assert resolve_baseline_schemes("D0") == ["D0"]
    assert resolve_baseline_schemes("MULTISURV") == ["MULTISURV"]
    assert str(baseline_scheme_output_dir("/tmp/out", "D0")) == "/tmp/out/D0"
    assert str(baseline_scheme_output_dir("/tmp/out", "HGCN_UCEC")) == "/tmp/out/baseline/HGCN_UCEC"


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
    _load_scheme_fields()
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

    out = run_json2prompt(
        json_path=str(json_path),
        scheme="INTEGRATIVE_DNN",
        template_dir=DEFAULT_TEMPLATE_DIR,
        prompt_dir=str(prompt_dir),
        dataset_name="TCGA-READ",
    )
    csv_path = Path(out)
    assert csv_path == prompt_dir / "INTEGRATIVE_DNN" / "prompts.csv"
    text = csv_path.read_text(encoding="utf-8")
    assert "Pathologic overall stage is Stage I." in text



def _tiny_case():
    return {
        "submitter_id": "TCGA-XX-0001",
        "demographic": {
            "age_at_index": 60,
            "sex_at_birth": "male",
            "race": "white",
            "ethnicity": "not hispanic or latino",
        },
        "diagnoses": [
            {
                "diagnosis_is_primary_disease": "true",
                "primary_diagnosis": "Adenocarcinoma",
                "morphology": "8140/3",
                "tissue_or_organ_of_origin": "Kidney, NOS",
                "laterality": "right",
                "year_of_diagnosis": 2012,
                "age_at_diagnosis": 21915,
                "tumor_grade": "G2",
                "prior_malignancy": "no",
                "synchronous_malignancy": "no",
                "prior_treatment": "No",
                "ajcc_pathologic_t": "T2",
                "ajcc_pathologic_n": "N0",
                "ajcc_pathologic_m": "M0",
                "ajcc_pathologic_stage": "Stage I",
                "ajcc_staging_system_edition": "7th",
                "pathology_details": [
                    {"lymph_nodes_tested": 12, "lymph_nodes_positive": 0}
                ],
            }
        ],
        "follow_ups": [
            {
                "ecog_performance_status": "1",
                "other_clinical_attributes": [{"bmi": 24.5}],
            }
        ],
        "project": {"project_id": "TCGA-KIRC"},
        "exposures": [
            {
                "pack_years_smoked": 20,
                "exposure_duration_years": 15,
                "cigarettes_per_day": 10,
                "alcohol_history": "yes",
            }
        ],
        "treatments": [
            {
                "treatment_type": "Pharmaceutical Therapy, NOS",
                "treatment_or_therapy": "yes",
            },
            {
                "treatment_type": "Radiation Therapy, NOS",
                "treatment_or_therapy": "no",
            },
        ],
    }


def test_extract_values_keeps_l5_and_paper_placeholders():
    values = extract_values(_tiny_case())
    assert set(L5_FIELDS).issubset(values)
    assert set(PAPER_FIELDS).issubset(values)
    assert set(values) == set(HUMAN_SCHEME_FIELDS)
    assert values["demographic.age_at_index"] == "60"
    assert values["diagnoses[].primary_diagnosis"] == "Adenocarcinoma"
    assert values["diagnoses[].tumor_grade"] == "G2"
    assert values["diagnoses[].ajcc_pathologic_t"] == "T2"
    assert values["follow_ups[].ecog_performance_status"] == "1"
    assert values["follow_ups[].other_clinical_attributes[].bmi"] == "24.5"
    assert values["project.project_id"] == "TCGA-KIRC"
    assert values["derived.pharmaceutical_therapy"] == "yes"
    assert values["derived.radiation_therapy"] == "no"
    assert values["exposures[].pack_years_smoked"] == "20"
    assert values["derived.years_smoked"] == "15"
    assert values["exposures[].cigarettes_per_day"] == "10"
    assert values["exposures[].alcohol_history"] == "yes"
    assert values["diagnoses[].site_of_resection_or_biopsy"] == "not reported"
    assert "TREATMENT_TYPE" not in values
    assert "SEX" not in values
    assert "SUBTYPE" not in values


def test_d_group_uses_gdc_dictionary_onehot_ordinary():
    _load_scheme_fields()
    ordinary = {
        "demographic.age_at_index",
        "diagnoses[].year_of_diagnosis",
        "diagnoses[].age_at_diagnosis",
        "diagnoses[].pathology_details[].lymph_nodes_tested",
        "diagnoses[].pathology_details[].lymph_nodes_positive",
        "follow_ups[].other_clinical_attributes[].bmi",
        "exposures[].pack_years_smoked",
        "derived.years_smoked",
        "exposures[].cigarettes_per_day",
    }
    onehot = set(HUMAN_SCHEME_FIELDS) - ordinary
    assert BASELINE_ORDINARY_FIELDS == ordinary
    assert BASELINE_ONEHOT_FIELDS == onehot
    assert BASELINE_DICTIONARY_FIELD_TYPES["diagnoses[].tumor_grade"] == "nominal"
    assert BASELINE_DICTIONARY_FIELD_TYPES["diagnoses[].ajcc_pathologic_stage"] == "nominal"
    assert BASELINE_DICTIONARY_FIELD_TYPES["follow_ups[].ecog_performance_status"] == "nominal"
    assert BASELINE_DICTIONARY_FIELD_TYPES["demographic.age_at_index"] == "continuous"
    assert BASELINE_DICTIONARY_FIELD_TYPES["project.project_id"] == "nominal"
    assert BASELINE_DICTIONARY_FIELD_TYPES["derived.years_smoked"] == "continuous"
    assert BASELINE_DICTIONARY_FIELD_TYPES["exposures[].pack_years_smoked"] == "continuous"
    assert BASELINE_DICTIONARY_FIELD_TYPES["derived.pharmaceutical_therapy"] == "nominal"
    assert baseline_field_encoding("diagnoses[].tumor_grade") == "onehot"
    assert baseline_field_encoding("diagnoses[].ajcc_pathologic_t") == "onehot"
    assert baseline_field_encoding("demographic.age_at_index") == "ordinary"
    schema_fields = set()
    for fields in BASELINE_SCHEME_FIELDS.values():
        schema_fields.update(fields)
    assert set(L5_FIELDS).issubset(schema_fields)
    assert set(PAPER_FIELDS).issubset(schema_fields)
    for scheme in PAPER_BASELINE_SCHEMES:
        assert scheme in BASELINE_SCHEME_FIELDS


def test_hgcn_keeps_old_field_types_and_cli():
    _load_scheme_fields()
    assert field_type_name("diagnoses[].tumor_grade") == "ordinal"
    assert field_type_name("diagnoses[].ajcc_pathologic_stage") == "ordinal"
    assert field_type_name("follow_ups[].ecog_performance_status") == "ordinal"
    assert field_type_name("demographic.age_at_index") == "continuous"
    assert field_type_name("diagnoses[].primary_diagnosis") == "nominal"
    assert BASELINE_ORDINAL_FIELDS == {
        "diagnoses[].tumor_grade",
        "diagnoses[].ajcc_pathologic_t",
        "diagnoses[].ajcc_pathologic_n",
        "diagnoses[].ajcc_pathologic_m",
        "diagnoses[].ajcc_pathologic_stage",
        "follow_ups[].ecog_performance_status",
    }
    assert BASELINE_CONTINUOUS_FIELDS == {
        "demographic.age_at_index",
        "diagnoses[].year_of_diagnosis",
        "diagnoses[].age_at_diagnosis",
        "diagnoses[].pathology_details[].lymph_nodes_tested",
        "diagnoses[].pathology_details[].lymph_nodes_positive",
        "follow_ups[].other_clinical_attributes[].bmi",
    }
    assert resolve_hgcn_schemes("all") == ["L0", "L1", "L2", "L3", "L4", "L5"]
    try:
        a_pipeline_main(["hgcn_clinic", "--help"])
    except SystemExit as exc:
        assert exc.code == 0


def test_d_group_onehot_mapping_does_not_change_hgcn_nominal_fit():
    rows = [
        {
            "diagnoses[].tumor_grade": "G2",
            "diagnoses[].ajcc_pathologic_t": "T2",
            "diagnoses[].primary_diagnosis": "Adenocarcinoma",
            "demographic.race": "white",
        },
        {
            "diagnoses[].tumor_grade": "G3",
            "diagnoses[].ajcc_pathologic_t": "T3",
            "diagnoses[].primary_diagnosis": "Adenocarcinoma",
            "demographic.race": "asian",
        },
    ]
    hgcn_mapping = fit_nominal_mappings(rows, min_count=1)
    d_mapping = fit_onehot_mappings(rows, min_count=1)
    assert set(hgcn_mapping) == BASELINE_NOMINAL_FIELDS
    assert "diagnoses[].tumor_grade" not in hgcn_mapping
    assert "diagnoses[].ajcc_pathologic_t" not in hgcn_mapping
    assert set(d_mapping) == BASELINE_ONEHOT_FIELDS
    assert "diagnoses[].tumor_grade" in d_mapping
    assert "diagnoses[].ajcc_pathologic_t" in d_mapping
    assert _encode_ordinal_value("diagnoses[].tumor_grade", "G2") == 2

    stats = {
        field: {"median": 0.0, "min": 0.0, "max": 1.0}
        for field in BASELINE_ORDINARY_FIELDS
    }
    vector = _build_baseline_vector(
        row={"diagnoses[].tumor_grade": "G2", "demographic.age_at_index": "60"},
        fields=["demographic.age_at_index", "diagnoses[].tumor_grade"],
        continuous_stats=stats,
        nominal_mappings=d_mapping,
    )
    grade_dim = len(d_mapping["diagnoses[].tumor_grade"])
    assert vector.shape == (1 + grade_dim,)
    grade_start = 1
    onehot = vector[grade_start:]
    assert int(onehot.sum()) == 1
    assert onehot[d_mapping["diagnoses[].tumor_grade"]["g2"]] == 1.0
