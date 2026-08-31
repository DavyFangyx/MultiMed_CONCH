"""Nested clinical JSON helpers used by A extract."""

from __future__ import annotations

from .missingness import clean_value


def unique_join(values: list, fallback="not reported") -> str:
    vals = [clean_value(v, "") for v in values]
    vals = sorted({x for x in vals if x})
    return ", ".join(vals) if vals else fallback


def get_primary_diagnosis(diagnoses: list) -> dict:
    if not diagnoses:
        return {}
    for item in diagnoses:
        if str(item.get("diagnosis_is_primary_disease", "")).lower() == "true":
            return item
    return diagnoses[0]


def get_treatments(case: dict) -> list:
    treatments = case.get("treatments", [])
    if not treatments:
        for diag in case.get("diagnoses", []):
            treatments = diag.get("treatments", [])
            if treatments:
                break
    return treatments or []


def get_pathology_details(case: dict) -> list:
    details = []
    for diag in case.get("diagnoses", []):
        details.extend(diag.get("pathology_details", []) or [])
    return details


def get_follow_ups(case: dict) -> list:
    return case.get("follow_ups", []) or []


def get_other_clinical_attributes(case: dict) -> list:
    attrs = []
    for follow_up in get_follow_ups(case):
        attrs.extend(follow_up.get("other_clinical_attributes", []) or [])
    return attrs
