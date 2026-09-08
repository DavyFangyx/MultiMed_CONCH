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
from src.cindex import claim_conf, conf_text, enqueue_cindex_jobs, expand_cindex_jobs, parse_conf, resolve_cindex_schemes, result_table_dir, run_claimed_conf, scheme_output_dir, summarize_dataset  # noqa: E402
from src.cli import main as a_pipeline_main  # noqa: E402
from src.config import ALL_TCGA_DATASETS, ALL_TEXT_SCHEMES, DEFAULT_TEXT_SCHEMES, PAPER_SCHEMES, SCHEME_DATASETS, SCHEME_FIELDS, SCHEME_TEMPLATE, load_custom_schemes, reset_scheme_registry, resolve_scheme_names, schemes_for_dataset  # noqa: E402
from src.config import SCHEME_CONFIG, scheme_source  # noqa: E402
from src.datasets import dataset_jobs, expand_source_jobs, load_dataset_configs, load_source_dataset_configs, resolve_dataset_names  # noqa: E402
from src.extract import extract_values  # noqa: E402
from src.hgcn_clinic import field_type_name, load_hgcn_scheme_fields, resolve_hgcn_schemes  # noqa: E402
from src.json2prompt import run_json2prompt  # noqa: E402
from src.paths import (  # noqa: E402
    A_PIPELINE_ROOT,
    DEFAULT_DATASETS_CONFIG,
    DEFAULT_GDC_DATASETS_CONFIG,
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
    assert SCHEME_DATASETS["L5"] is None
    assert "D0" not in SCHEME_DATASETS
    assert len(ALL_TCGA_DATASETS) == 33
    for name in PAPER_SCHEMES:
        assert SCHEME_DATASETS[name] == list(ALL_TCGA_DATASETS)
    datasets = {name: {} for name in ALL_TCGA_DATASETS}
    assert schemes_for_dataset(["L0", "HGCN_KIRC", "MMSURV"], "TCGA-KIRC", datasets) == ["L0", "HGCN_KIRC", "MMSURV"]
    assert schemes_for_dataset(["L0", "HGCN_KIRC", "MMSURV"], "TCGA-READ", datasets) == ["L0", "HGCN_KIRC", "MMSURV"]
    assert schemes_for_dataset(["L0", "HGCN_KIRC", "MMSURV"], "TCGA-ESCA", datasets) == ["L0", "HGCN_KIRC", "MMSURV"]
    assert schemes_for_dataset(["D0", "HGCN_KIRC"], "TCGA-KIRC", datasets) == ["D0", "HGCN_KIRC"]
    assert schemes_for_dataset(["D0", "HGCN_KIRC"], "TCGA-READ", datasets) == ["D0", "HGCN_KIRC"]
    assert schemes_for_dataset(["HGCN_LIHC"], "TCGA-LIHC", datasets) == ["HGCN_LIHC"]
    assert schemes_for_dataset(["HGCN_KIRC"], None, datasets) == ["HGCN_KIRC"]


def test_scheme_sources_are_lizhe_or_gdc():
    _load_scheme_fields()
    for name in DEFAULT_TEXT_SCHEMES:
        assert SCHEME_CONFIG[name]["source"] == "lizhe"
        assert scheme_source(name) == "lizhe"
        d_name = name.replace("L", "D", 1)
        assert scheme_source(d_name) == "lizhe"
    for name in PAPER_SCHEMES:
        assert SCHEME_CONFIG[name]["source"] == "gdc"
        assert scheme_source(name) == "gdc"


def test_scheme_loader_skips_field_bank():
    _load_scheme_fields()
    assert resolve_scheme_names("manual") == ["L0", "L1", "L2", "L3", "L4", "L5"]
    assert resolve_scheme_names("paper") == list(PAPER_SCHEMES)
    assert resolve_scheme_names("all") == list(ALL_TEXT_SCHEMES)
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


def test_expand_source_jobs_uses_scheme_source():
    _load_scheme_fields()
    source_datasets = load_source_dataset_configs(
        lizhe_config=DEFAULT_DATASETS_CONFIG,
        gdc_config=DEFAULT_GDC_DATASETS_CONFIG,
    )
    jobs = expand_source_jobs(
        "all",
        ["L0", "MULTISURV", "HGCN_ESCA"],
        source_datasets,
        json_path="unused.json",
        prompt_dir="/tmp/unused_prompt",
        out_dir="/tmp/unused_out",
        baseline_out="/tmp/outputs",
    )
    by_key = {(job["source"], job["name"]): job for job in jobs}
    assert ("lizhe", "TCGA-BRCA") in by_key
    assert ("gdc", "TCGA-BRCA") in by_key
    assert by_key[("lizhe", "TCGA-BRCA")]["schemes"] == ["L0"]
    assert "MULTISURV" in by_key[("gdc", "TCGA-BRCA")]["schemes"]
    assert by_key[("lizhe", "TCGA-BRCA")]["json_paths"][0].startswith("/data/lizhe/")
    assert "gdc_clinical/raw_json" in by_key[("gdc", "TCGA-BRCA")]["json_paths"][0]
    assert by_key[("gdc", "TCGA-ESCA")]["schemes"] == ["MULTISURV", "HGCN_ESCA"]
    assert "MULTISURV" in by_key[("gdc", "TCGA-GBM")]["schemes"]
    assert "HGCN_ESCA" in by_key[("gdc", "TCGA-GBM")]["schemes"]
    assert ("lizhe", "TCGA-ESCA") not in by_key
    assert ("lizhe", "TCGA-GBM") not in by_key

    esca_manual = expand_source_jobs(
        "TCGA-ESCA",
        ["L0"],
        source_datasets,
        json_path="unused.json",
        prompt_dir="/tmp/unused_prompt",
        out_dir="/tmp/unused_out",
        baseline_out="/tmp/outputs",
    )
    assert esca_manual == []

    paper_jobs = expand_source_jobs(
        "all",
        ["SURVPGC"],
        source_datasets,
        json_path="unused.json",
        prompt_dir="/tmp/unused_prompt",
        out_dir="/tmp/unused_out",
        baseline_out="/tmp/outputs",
    )
    paper_names = [job["name"] for job in paper_jobs if job["source"] == "gdc"]
    assert paper_names == sorted(ALL_TCGA_DATASETS)
    assert set(paper_names) == set(ALL_TCGA_DATASETS)
    assert len(paper_names) == 33
    assert all(job["schemes"] == ["SURVPGC"] for job in paper_jobs)


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
    assert resolve_baseline_schemes("manual") == ["D0", "D1", "D2", "D3", "D4", "D5"]
    assert resolve_baseline_schemes("paper") == list(PAPER_SCHEMES)
    assert resolve_baseline_schemes("all") == ["D0", "D1", "D2", "D3", "D4", "D5"] + list(PAPER_SCHEMES)
    assert resolve_baseline_schemes("D0") == ["D0"]
    assert resolve_baseline_schemes("MULTISURV") == ["MULTISURV"]
    assert str(baseline_scheme_output_dir("/tmp/out", "D0")) == "/tmp/out/D0"
    assert str(baseline_scheme_output_dir("/tmp/out", "HGCN_UCEC")) == "/tmp/out/baseline/HGCN_UCEC"


def test_global_mapping_dir_lives_in_a_pipeline():
    mapping_dir = global_mapping_dir()
    assert mapping_dir == A_PIPELINE_ROOT / "baseline_onehot_mapping_tables"
    assert mapping_dir.parent == A_PIPELINE_ROOT
    assert "outputs" not in mapping_dir.parts[-3:]
    assert global_mapping_dir("lizhe") == mapping_dir
    assert global_mapping_dir("gdc") == mapping_dir / "gdc"


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
    assert resolve_hgcn_schemes("manual") == ["L0", "L1", "L2", "L3", "L4", "L5"]
    try:
        resolve_hgcn_schemes("paper")
        raise AssertionError("hgcn paper should be rejected")
    except ValueError as exc:
        assert "L0-L5" in str(exc)
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


def test_cindex_jobs_follow_scheme_bindings():
    _load_scheme_fields()
    datasets = {"TCGA-KIRC": {}, "TCGA-READ": {}, "TCGA_LIHC": {}}
    schemes = resolve_cindex_schemes("all", "all")
    assert schemes[:6] == ["L0", "L1", "L2", "L3", "L4", "L5"]
    assert "D0" not in schemes
    assert "MULTISURV" in schemes
    assert "HGCN_KIRC" in schemes
    assert resolve_cindex_schemes("all", "text") == schemes
    assert resolve_cindex_schemes("all", "baseline") == schemes
    assert resolve_cindex_schemes("manual", "all") == ["L0", "L1", "L2", "L3", "L4", "L5"]
    assert [job["scheme"] for job in expand_cindex_jobs(resolve_cindex_schemes("manual", "text"), "text")] == [
        "L0", "L1", "L2", "L3", "L4", "L5"
    ]
    assert [job["scheme"] for job in expand_cindex_jobs(resolve_cindex_schemes("manual", "baseline"), "baseline")] == [
        "D0", "D1", "D2", "D3", "D4", "D5"
    ]
    assert resolve_cindex_schemes("paper", "text") == [
        "MULTISURV",
        "SURVPGC",
        "MMSURV",
        "INTEGRATIVE_DNN",
        "HGCN_KIRC",
        "HGCN_LIHC",
        "HGCN_ESCA",
        "HGCN_LUSC",
        "HGCN_LUAD",
        "HGCN_UCEC",
    ]
    assert schemes_for_dataset(["L0", "D0", "HGCN_KIRC"], "TCGA-KIRC", datasets) == ["L0", "D0", "HGCN_KIRC"]
    assert schemes_for_dataset(["L0", "D0", "HGCN_KIRC"], "TCGA-READ", datasets) == ["L0", "D0", "HGCN_KIRC"]
    jobs = expand_cindex_jobs(["HGCN_KIRC"], "all")
    assert [job["scheme"] for job in jobs] == ["HGCN_KIRC", "baseline__HGCN_KIRC"]
    jobs = expand_cindex_jobs(["HGCN_KIRC"], "baseline")
    assert [job["scheme"] for job in jobs] == ["baseline__HGCN_KIRC"]
    jobs = expand_cindex_jobs(["L4"], "all")
    assert [job["scheme"] for job in jobs] == ["L4", "D4"]
    jobs = expand_cindex_jobs(["L4"], "baseline")
    assert [job["scheme"] for job in jobs] == ["D4"]


def test_cindex_output_paths():
    prompt_dir = scheme_output_dir("TCGA-READ", "L0", "/tmp/outputs")
    baseline_dir = scheme_output_dir("TCGA-READ", "D0", "/tmp/outputs")
    paper_baseline_dir = scheme_output_dir("TCGA-KIRC", "baseline__HGCN_KIRC", "/tmp/outputs")
    assert str(prompt_dir).endswith("/outputs/TCGA-READ/A_manual/L0/embeddings/pt")
    assert str(baseline_dir) == "/tmp/outputs/TCGA-READ/A_manual/D0/embeddings/pt"
    assert str(paper_baseline_dir) == "/tmp/outputs/TCGA-KIRC/A_manual/baseline/HGCN_KIRC/embeddings/pt"
    table_dir = result_table_dir("TCGA-READ")
    assert table_dir.as_posix().endswith("/results/A_manual/TCGA-READ")
    assert "Clinic_Analyzer" not in table_dir.parts



def test_cindex_queue_conf_and_claim(tmp_path, monkeypatch):
    queue_root = tmp_path / "queue_root"
    clinic_dir = tmp_path / "clinic"
    clinic_dir.mkdir()
    split_dir = tmp_path / "splits"
    split_dir.mkdir()
    results_base = tmp_path / "results"
    jobs = [
        {
            "study": "tcga_read",
            "scheme": "L0",
            "modality": "mlp_clinic_flatten",
            "clinic_dir": clinic_dir,
            "split_dir": split_dir,
            "results_base": results_base,
            "seed": 0,
            "max_epochs": 2,
            "conf_name": "tcga_read__L0__mlp_clinic_flatten.conf",
        }
    ]
    queued = enqueue_cindex_jobs(jobs, queue_root=queue_root)
    assert len(queued["created"]) == 1
    conf_path = queued["created"][0]
    payload = parse_conf(conf_path)
    assert payload["EXP_GROUP"] == "A_manual/runs"
    assert payload["RUN_NAME"] == "tcga_read__L0"
    assert payload["PRESET"] == "mlp_clinic_flatten"
    assert payload["STUDY"] == "tcga_read"
    assert payload["CLINIC_DIR_PATH"] == str(clinic_dir)
    assert payload["SPLIT_DIR_PATH"] == str(split_dir)
    assert payload["RESULTS_BASE"] == str(results_base)
    assert payload["SEED"] == "0"
    assert payload["MAX_EPOCHS"] == "2"
    assert payload["WANDB_MODE"] == "disabled"
    assert "CLINIC_DIR_PATH=" in conf_text(
        study="tcga_read",
        scheme="L0",
        modality="mlp_clinic_flatten",
        clinic_dir=clinic_dir,
        split_dir=split_dir,
        results_base=results_base,
    )

    again = enqueue_cindex_jobs(jobs, queue_root=queue_root)
    assert again["created"] == []
    assert len(again["existing"]) == 1

    claimed = claim_conf(queue_root)
    assert claimed is not None
    assert claimed.parent.name == "running"
    assert not (queue_root / "queue" / claimed.name).exists()
    assert claim_conf(queue_root) is None

    out_dir = results_base / "A_manual" / "runs" / "tcga_read__L0" / "mlp_clinic_flatten"
    out_dir.mkdir(parents=True)
    (out_dir / "val_result_fold0.csv").write_text("val_cindex\n0.7\n", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise AssertionError("run.sh should not be called on reuse")

    monkeypatch.setattr("src.cindex.subprocess.run", _boom)
    dest = run_claimed_conf(claimed, reuse=True)
    assert dest.parent.name == "done"
    assert dest.name == claimed.name
    assert (out_dir / "run.log").as_posix().endswith("/A_manual/runs/tcga_read__L0/mlp_clinic_flatten/run.log")

    failed = queue_root / "failed" / dest.name
    failed.parent.mkdir(parents=True, exist_ok=True)
    dest.replace(failed)
    retried = enqueue_cindex_jobs(jobs, queue_root=queue_root)
    assert len(retried["created"]) == 1
    assert retried["created"][0].parent.name == "queue"
    assert not failed.exists()


def test_cindex_workers_claim_in_parallel(tmp_path, monkeypatch):
    from src.cindex import drain_queue, enqueue_cindex_jobs

    queue_root = tmp_path / "queue_root"
    clinic_dir = tmp_path / "clinic"
    clinic_dir.mkdir()
    split_dir = tmp_path / "splits"
    split_dir.mkdir()
    results_base = tmp_path / "results"
    jobs = []
    for idx, modality in enumerate(["mlp_clinic_flatten", "snn_clinic_flatten"]):
        jobs.append(
            {
                "study": "tcga_read",
                "scheme": "L0",
                "modality": modality,
                "clinic_dir": clinic_dir,
                "split_dir": split_dir,
                "results_base": results_base,
                "seed": 0,
                "conf_name": f"tcga_read__L0__{modality}.conf",
            }
        )
        out_dir = results_base / "A_manual" / "runs" / "tcga_read__L0" / modality
        out_dir.mkdir(parents=True)
        (out_dir / "val_result_fold0.csv").write_text("val_cindex\n0.7\n", encoding="utf-8")
        (out_dir / "run.log").write_text("ok\n", encoding="utf-8")
    enqueue_cindex_jobs(jobs, queue_root=queue_root)
    seen = []

    def _record(claimed, reuse=True):
        seen.append(claimed.name)
        from src.cindex import mark_done
        return mark_done(claimed)

    monkeypatch.setattr("src.cindex.run_claimed_conf", _record)
    drain_queue(queue_root, reuse=True, poll_seconds=0.01, workers=2)
    assert sorted(seen) == [
        "tcga_read__L0__mlp_clinic_flatten.conf",
        "tcga_read__L0__snn_clinic_flatten.conf",
    ]
    assert not list((queue_root / "queue").glob("*.conf"))
    assert sorted(path.name for path in (queue_root / "done").glob("*.conf")) == sorted(seen)


def test_summarize_dataset_adds_new_modality_without_overwriting(tmp_path):
    results_root = tmp_path / "results"
    table_dir = results_root / "A_manual" / "TCGA_LIHC"
    table_dir.mkdir(parents=True)
    existing = [
        {
            "dataset": "TCGA_LIHC",
            "scheme": "MULTISURV",
            "encoding": "prompt",
            "modality": "mlp_clinic_flatten",
            "clinic_dir": "old_clinic",
            "results_dir": "old_results",
            "log_path": "old.log",
            "skipped": True,
            "val_c_index_mean": 0.62,
            "val_c_index_std": 0.01,
            "test_c_index_mean": 0.62,
            "test_c_index_std": 0.01,
            "source": "val",
        }
    ]
    from src.cindex import _write_csv, _write_json
    _write_csv(table_dir / "cindex.csv", existing)
    _write_json(table_dir / "run_config.json", {"dataset": "TCGA_LIHC", "rows": existing, "modalities": ["mlp_clinic_flatten"]})
    cox_dir = results_root / "A_manual" / "runs" / "tcga_lihc__MULTISURV" / "clinic_cox"
    cox_dir.mkdir(parents=True)
    (cox_dir / "val_result_fold0.csv").write_text("val_cindex\n0.55\n", encoding="utf-8")
    (cox_dir / "run.log").write_text("ok\n", encoding="utf-8")
    jobs = [
        {
            "scheme": "MULTISURV",
            "encoding": "prompt",
            "modality": "clinic_cox",
            "clinic_dir": tmp_path / "clinic",
            "out_dir": cox_dir,
        }
    ]
    rows = summarize_dataset(
        dataset_name="TCGA_LIHC",
        jobs=jobs,
        results_root=results_root,
        encoding="text",
        modality="clinic_cox",
    )
    modalities = [row["modality"] for row in rows]
    assert modalities == ["mlp_clinic_flatten", "clinic_cox"]
    assert rows[0]["val_c_index_mean"] == 0.62
    assert float(rows[1]["val_c_index_mean"]) == 0.55
