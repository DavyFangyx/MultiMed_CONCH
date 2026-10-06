from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from common.paths import RESULTS_ROOT, test_results_dir as _resolve_results_dir  # noqa: E402

# Test 系列命名公约: 结果臂目录(迁移前 = A_manual/A_manual_landmark,
# 迁移后 = Test_2b/arm_A/arm_B;断言随解析,两种状态都成立)
ARM_A = _resolve_results_dir("Test_2b/arm_A").relative_to(RESULTS_ROOT)
ARM_B = _resolve_results_dir("Test_2b/arm_B").relative_to(RESULTS_ROOT)

from manual_pipeline.baseline import (  # noqa: E402
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
from manual_pipeline.cindex import claim_conf, conf_text, enqueue_cindex_jobs, expand_cindex_jobs, parse_conf, resolve_cindex_schemes, result_table_dir, run_claimed_conf, scheme_output_dir, summarize_dataset  # noqa: E402
from manual_pipeline.cli import main as manual_main  # noqa: E402
from manual_pipeline.config import ALL_TCGA_DATASETS, ALL_TEXT_SCHEMES, PAPER_SCHEMES, SCHEME_DATASETS, SCHEME_FIELDS, SCHEME_TEMPLATE, load_custom_schemes, reset_scheme_registry, resolve_scheme_names, schemes_for_dataset  # noqa: E402
from manual_pipeline.config import SCHEME_CONFIG, scheme_source  # noqa: E402
from manual_pipeline.datasets import dataset_jobs, expand_source_jobs, load_dataset_configs, load_source_dataset_configs, resolve_dataset_names  # noqa: E402
from manual_pipeline.extract import extract_values  # noqa: E402
from manual_pipeline.hgcn_clinic import field_type_name, load_hgcn_scheme_fields, resolve_hgcn_schemes  # noqa: E402
from manual_pipeline.json2prompt import run_json2prompt  # noqa: E402
from manual_pipeline.paths import (  # noqa: E402
    DEFAULT_GDC_DATASETS_CONFIG,
    DEFAULT_TEMPLATE_DIR,
    TEMPLATES_ROOT,
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
    assert list(PAPER_SCHEMES) == paper  # L0-L5 已随 PGC 线移除：全部文本方案 = 论文方案
    for name in ALL_TEXT_SCHEMES:
        assert name in SCHEME_FIELDS
        assert SCHEME_TEMPLATE[name] == f"{name}/template.csv"
        scheme_dir = Path(DEFAULT_TEMPLATE_DIR) / name
        assert (scheme_dir / "fields.json").exists()
        assert (scheme_dir / "template.csv").exists()
        assert SCHEME_FIELDS[name]


def test_scheme_dataset_bindings():
    _load_scheme_fields()
    assert "L0" not in SCHEME_DATASETS  # L0-L5 已随 PGC 线移除
    assert "D0" not in SCHEME_DATASETS
    assert len(ALL_TCGA_DATASETS) == 33
    for name in PAPER_SCHEMES:
        assert SCHEME_DATASETS[name] == list(ALL_TCGA_DATASETS)
    datasets = {name: {} for name in ALL_TCGA_DATASETS}
    assert schemes_for_dataset(["MULTISURV", "HGCN_KIRC", "MMSURV"], "TCGA-KIRC", datasets) == ["MULTISURV", "HGCN_KIRC", "MMSURV"]
    assert schemes_for_dataset(["MULTISURV", "HGCN_KIRC", "MMSURV"], "TCGA-READ", datasets) == ["MULTISURV", "HGCN_KIRC", "MMSURV"]
    assert schemes_for_dataset(["MULTISURV", "HGCN_KIRC", "MMSURV"], "TCGA-ESCA", datasets) == ["MULTISURV", "HGCN_KIRC", "MMSURV"]
    assert schemes_for_dataset(["HGCN_LIHC"], "TCGA-LIHC", datasets) == ["HGCN_LIHC"]
    assert schemes_for_dataset(["HGCN_KIRC"], None, datasets) == ["HGCN_KIRC"]


def test_scheme_sources_are_all_gdc():
    _load_scheme_fields()
    for name in SCHEME_CONFIG:
        assert scheme_source(name) == "gdc"
    assert scheme_source("NOT_REGISTERED") is None


def test_scheme_loader_skips_field_bank():
    _load_scheme_fields()
    try:
        resolve_scheme_names("manual")
        raise AssertionError("manual (L0-L5) should be rejected")
    except ValueError as exc:
        assert "PGC 线" in str(exc)
    assert resolve_scheme_names("paper") == list(PAPER_SCHEMES)
    assert resolve_scheme_names("all") == list(ALL_TEXT_SCHEMES)
    assert resolve_scheme_names("MULTISURV") == ["MULTISURV"]
    try:
        resolve_scheme_names("FIELD_BANK")
        raise AssertionError("FIELD_BANK should be rejected")
    except ValueError as exc:
        assert "FIELD_BANK" in str(exc)


def test_default_datasets_are_gdc_official():
    """gdc 线唯一数据源 = projects/datasets.json（官方 33 队列 + MMRF/CPTAC）。"""
    assert DEFAULT_GDC_DATASETS_CONFIG.endswith("/projects/datasets.json")
    datasets = load_dataset_configs(DEFAULT_GDC_DATASETS_CONFIG)
    names = resolve_dataset_names("all", datasets)
    assert len(ALL_TCGA_DATASETS) == 33
    assert set(ALL_TCGA_DATASETS).issubset(names)
    assert {"MMRF", "CPTAC"}.issubset(names)
    for cfg in datasets.values():
        assert all("gdc_clinical/raw_json" in path for path in cfg["clinic_files"])


def test_expand_source_jobs_uses_scheme_source():
    """gdc 线只有 gdc 来源；未注册方案（如 L0，已随 PGC 线移除）→ 跳过而不是报错。"""
    _load_scheme_fields()
    source_datasets = load_source_dataset_configs(gdc_config=DEFAULT_GDC_DATASETS_CONFIG)
    assert list(source_datasets) == ["gdc"]
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
    assert all(job["source"] == "gdc" for job in jobs)
    assert ("gdc", "TCGA-BRCA") in by_key
    assert "MULTISURV" in by_key[("gdc", "TCGA-BRCA")]["schemes"]
    assert "gdc_clinical/raw_json" in by_key[("gdc", "TCGA-BRCA")]["json_paths"][0]
    assert "L0" not in by_key[("gdc", "TCGA-BRCA")]["schemes"]     # L0 未注册，已跳过
    assert by_key[("gdc", "TCGA-ESCA")]["schemes"] == ["MULTISURV", "HGCN_ESCA"]
    assert "MULTISURV" in by_key[("gdc", "TCGA-GBM")]["schemes"]
    assert "HGCN_ESCA" in by_key[("gdc", "TCGA-GBM")]["schemes"]

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


def test_baseline_schemes_are_paper_only():
    _load_scheme_fields()
    try:
        resolve_baseline_schemes("manual")
        raise AssertionError("manual (D0-D5) should be rejected")
    except ValueError as exc:
        assert "PGC 线" in str(exc)
    assert resolve_baseline_schemes("paper") == list(PAPER_SCHEMES)
    assert resolve_baseline_schemes("all") == list(PAPER_SCHEMES)
    assert resolve_baseline_schemes("MULTISURV") == ["MULTISURV"]
    assert str(baseline_scheme_output_dir("/tmp/out", "HGCN_UCEC")) == "/tmp/out/baseline/HGCN_UCEC"


def test_global_mapping_dir_lives_in_manual_templates():
    mapping_dir = global_mapping_dir()
    assert mapping_dir == TEMPLATES_ROOT / "baseline_onehot_mapping_tables"
    assert mapping_dir.parent == TEMPLATES_ROOT
    assert "outputs" not in mapping_dir.parts[-3:]
    assert global_mapping_dir() == mapping_dir


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
        scheme="MULTISURV",
        template_dir=DEFAULT_TEMPLATE_DIR,
        prompt_dir=str(prompt_dir),
        dataset_name="TCGA-READ",
    )
    csv_path = Path(out)
    assert csv_path == prompt_dir / "MULTISURV" / "prompts.csv"
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
    assert resolve_hgcn_schemes("all") == list(PAPER_SCHEMES)
    try:
        resolve_hgcn_schemes("manual")
        raise AssertionError("manual (L0-L5) should be rejected")
    except ValueError as exc:
        assert "PGC 线" in str(exc)
    # S11：论文 / templates 自定义方案显式点名可编码（节点名 = fields.json 字段路径）
    assert resolve_hgcn_schemes("paper") == list(PAPER_SCHEMES)
    assert resolve_hgcn_schemes("MULTISURV") == ["MULTISURV"]
    assert resolve_hgcn_schemes("Test_3_greedy_TCGA-LAML") == ["Test_3_greedy_TCGA-LAML"]
    try:
        resolve_hgcn_schemes("NOT_A_SCHEME")
        raise AssertionError("unknown scheme should be rejected")
    except ValueError as exc:
        assert "NOT_A_SCHEME" in str(exc)
    try:
        manual_main(["hgcn_clinic", "--help"])
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
    assert "D0" not in schemes
    assert "L0" not in schemes  # L0-L5 已随 PGC 线移除
    assert "MULTISURV" in schemes
    assert "HGCN_KIRC" in schemes
    assert resolve_cindex_schemes("all", "text") == schemes
    assert resolve_cindex_schemes("all", "baseline") == schemes
    for encoding in ("all", "text", "baseline"):
        try:
            resolve_cindex_schemes("manual", encoding)
            raise AssertionError("manual (L0-L5 / D0-D5) should be rejected")
        except ValueError as exc:
            assert "PGC 线" in str(exc)
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
    assert schemes_for_dataset(["MULTISURV", "SURVPGC", "HGCN_KIRC"], "TCGA-KIRC", datasets) == ["MULTISURV", "SURVPGC", "HGCN_KIRC"]
    assert schemes_for_dataset(["MULTISURV", "SURVPGC", "HGCN_KIRC"], "TCGA-READ", datasets) == ["MULTISURV", "SURVPGC", "HGCN_KIRC"]
    jobs = expand_cindex_jobs(["HGCN_KIRC"], "all")
    assert [job["scheme"] for job in jobs] == ["HGCN_KIRC", "baseline__HGCN_KIRC"]
    jobs = expand_cindex_jobs(["HGCN_KIRC"], "baseline")
    assert [job["scheme"] for job in jobs] == ["baseline__HGCN_KIRC"]


def test_cindex_output_paths():
    prompt_dir = scheme_output_dir("TCGA-READ", "MULTISURV", "/tmp/outputs")
    paper_baseline_dir = scheme_output_dir("TCGA-KIRC", "baseline__HGCN_KIRC", "/tmp/outputs")
    assert str(prompt_dir).endswith("/outputs/TCGA-READ/A_manual/MULTISURV/embeddings/pt")
    assert str(paper_baseline_dir) == "/tmp/outputs/TCGA-KIRC/A_manual/baseline/HGCN_KIRC/embeddings/pt"
    table_dir = result_table_dir("TCGA-READ")
    assert table_dir.as_posix().endswith(f"/results/{ARM_A}/TCGA-READ")
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
    assert payload["EXP_GROUP"] == f"{ARM_A}/runs"
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

    out_dir = results_base / ARM_A / "runs" / "tcga_read__L0" / "mlp_clinic_flatten"
    out_dir.mkdir(parents=True)
    # existing_result_dir 要求 5 折 val CSV 齐全（被杀中途的半成品不复用）
    for fold in range(5):
        (out_dir / f"val_result_fold{fold}.csv").write_text("val_cindex\n0.7\n", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise AssertionError("run.sh should not be called on reuse")

    monkeypatch.setattr("manual_pipeline.cindex.subprocess.run", _boom)
    dest = run_claimed_conf(claimed, reuse=True)
    assert dest.parent.name == "done"
    assert dest.name == claimed.name
    assert (out_dir / "run.log").as_posix().endswith(f"/{ARM_A}/runs/tcga_read__L0/mlp_clinic_flatten/run.log")

    failed = queue_root / "failed" / dest.name
    failed.parent.mkdir(parents=True, exist_ok=True)
    dest.replace(failed)
    retried = enqueue_cindex_jobs(jobs, queue_root=queue_root)
    assert len(retried["created"]) == 1
    assert retried["created"][0].parent.name == "queue"
    assert not failed.exists()


def test_cindex_workers_claim_in_parallel(tmp_path, monkeypatch):
    from manual_pipeline.cindex import drain_queue, enqueue_cindex_jobs

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
        out_dir = results_base / ARM_A / "runs" / "tcga_read__L0" / modality
        out_dir.mkdir(parents=True)
        (out_dir / "val_result_fold0.csv").write_text("val_cindex\n0.7\n", encoding="utf-8")
        (out_dir / "run.log").write_text("ok\n", encoding="utf-8")
    enqueue_cindex_jobs(jobs, queue_root=queue_root)
    seen = []

    def _record(claimed, reuse=True):
        seen.append(claimed.name)
        from manual_pipeline.cindex import mark_done
        return mark_done(claimed)

    monkeypatch.setattr("manual_pipeline.cindex.run_claimed_conf", _record)
    drain_queue(queue_root, reuse=True, poll_seconds=0.01, workers=2)
    assert sorted(seen) == [
        "tcga_read__L0__mlp_clinic_flatten.conf",
        "tcga_read__L0__snn_clinic_flatten.conf",
    ]
    assert not list((queue_root / "queue").glob("*.conf"))
    assert sorted(path.name for path in (queue_root / "done").glob("*.conf")) == sorted(seen)


def test_summarize_dataset_adds_new_modality_without_overwriting(tmp_path):
    results_root = tmp_path / "results"
    table_dir = results_root / ARM_A / "TCGA_LIHC"
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
    from manual_pipeline.cindex import _write_csv, _write_json
    _write_csv(table_dir / "cindex.csv", existing)
    _write_json(table_dir / "run_config.json", {"dataset": "TCGA_LIHC", "rows": existing, "modalities": ["mlp_clinic_flatten"]})
    cox_dir = results_root / "A_manual" / "runs" / "tcga_lihc__MULTISURV" / "clinic_cox"
    cox_dir.mkdir(parents=True)
    for fold in range(5):
        (cox_dir / f"val_result_fold{fold}.csv").write_text("val_cindex\n0.55\n", encoding="utf-8")
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
