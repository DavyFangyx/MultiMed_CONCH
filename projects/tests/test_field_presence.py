from pathlib import Path
import sys

import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from discovery.presence import (
    align_scan_path_to_mapping,
    build_not_in_table_census,
    census_dataset_presence,
    strip_array_markers,
)
from discovery.scan import parse_field_dictionary


def test_strip_array_markers_and_alignment():
    assert strip_array_markers("diagnoses[].age_at_diagnosis") == "diagnoses.age_at_diagnosis"
    assert (
        align_scan_path_to_mapping("diagnoses[].treatments[].treatment_type")
        == "diagnoses.treatments.treatment_type"
    )
    assert (
        align_scan_path_to_mapping("follow_ups[].molecular_tests[].gene_symbol")
        == "follow_ups.molecular_tests.gene_symbol"
    )
    assert align_scan_path_to_mapping("case_id") == "case_id"
    assert align_scan_path_to_mapping("project.project_id") == "project.project_id"


def test_nested_ids_are_not_collapsed():
    assert align_scan_path_to_mapping("diagnoses[].submitter_id") == "diagnoses.submitter_id"
    assert align_scan_path_to_mapping("submitter_id") == "submitter_id"
    assert align_scan_path_to_mapping("diagnoses[].submitter_id") != align_scan_path_to_mapping("submitter_id")


def test_container_leaves_are_not_in_table():
    dict_data = {
        "_meta": {"n_cases": 2},
        "顶层字段": {"case_id": "id", "project": "container", "diagnoses": "container"},
        "project对象": {"project_id": "project id"},
        "diagnoses数组_每个对象": {"age_at_diagnosis": "age", "treatments": "container"},
        "_section_prefixes": {
            "顶层字段": "",
            "project对象": "project",
            "diagnoses数组_每个对象": "diagnoses[]",
        },
    }
    mapping = pd.DataFrame(
        [
            {"field": "case_id", "entity": "case"},
            {"field": "project.project_id", "entity": "project"},
            {"field": "diagnoses.age_at_diagnosis", "entity": "diagnosis"},
            {"field": "diagnoses.primary_diagnosis", "entity": "diagnosis"},
        ]
    )
    presence, summary = census_dataset_presence("TCGA-BRCA", dict_data, mapping)
    by_field = presence.set_index("mapping_field")["status"].to_dict()
    scan_by_field = presence.set_index("mapping_field")["scan_field_path"].to_dict()

    assert by_field["case_id"] == "in_table_and_data"
    assert scan_by_field["case_id"] == "case_id"
    assert by_field["project.project_id"] == "in_table_and_data"
    assert scan_by_field["project.project_id"] == "project.project_id"
    assert by_field["diagnoses.age_at_diagnosis"] == "in_table_and_data"
    assert scan_by_field["diagnoses.age_at_diagnosis"] == "diagnoses[].age_at_diagnosis"
    assert by_field["diagnoses.primary_diagnosis"] == "in_table_not_data"
    assert scan_by_field["diagnoses.primary_diagnosis"] == ""

    extras = presence.loc[presence["status"] == "not_in_table", "mapping_field"].tolist()
    assert extras == ["diagnoses", "diagnoses.treatments", "project"]
    assert summary["n_mapping_fields"] == 4
    assert summary["n_scanned_fields"] == len(parse_field_dictionary(dict_data))
    assert summary["in_table_and_data"] == 3
    assert summary["in_table_not_data"] == 1
    assert summary["not_in_table"] == 3
    assert summary["in_table_and_data"] + summary["in_table_not_data"] == 4
    assert summary["in_table_and_data"] + summary["not_in_table"] == summary["n_scanned_fields"]

def test_not_in_table_census_by_field_name():
    mapping = pd.DataFrame([{"field": "case_id", "entity": "case"}])
    dict_a = {
        "_meta": {"n_cases": 1},
        "顶层字段": {"case_id": "id", "project": "container", "diagnoses": "container"},
        "_section_prefixes": {"顶层字段": ""},
    }
    dict_b = {
        "_meta": {"n_cases": 1},
        "顶层字段": {"case_id": "id", "project": "container", "family_histories": "container"},
        "_section_prefixes": {"顶层字段": ""},
    }
    presence_a, _ = census_dataset_presence("TCGA-BRCA", dict_a, mapping)
    presence_b, _ = census_dataset_presence("TCGA-COAD", dict_b, mapping)
    extras = build_not_in_table_census(
        [presence_a, presence_b],
        ["TCGA-BRCA", "TCGA-COAD"],
    )
    by_field = extras.set_index("mapping_field")
    assert list(extras["mapping_field"]) == ["diagnoses", "family_histories", "project"]
    assert by_field.loc["project", "n_datasets_present"] == 2
    assert by_field.loc["project", "present_datasets"] == "TCGA-BRCA,TCGA-COAD"
    assert by_field.loc["diagnoses", "n_datasets_present"] == 1
    assert by_field.loc["diagnoses", "present_datasets"] == "TCGA-BRCA"
    assert by_field.loc["family_histories", "present_datasets"] == "TCGA-COAD"
    assert by_field.loc["diagnoses", "scan_field_path"] == "diagnoses"

