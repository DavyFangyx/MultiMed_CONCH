"""Shared type inference for clinical fields."""

from __future__ import annotations

import re


ORDINAL_NAME_TOKENS = (
    "grade",
    "stage",
    "ajcc_pathologic_t",
    "ajcc_pathologic_n",
    "ajcc_pathologic_m",
    "ecog",
    "performance",
)
ORDINAL_VALUE_RE = re.compile(r"^(g|t|n|m|stage\s)", re.IGNORECASE)


def to_numeric(value):
    try:
        if isinstance(value, bool):
            return float(int(value))
        return float(value)
    except Exception:
        return None


def infer_type(field_name: str, valid_values: list, unique_count: int) -> str:
    if not valid_values:
        return "empty"
    numeric_hits = 0
    for value in valid_values:
        if to_numeric(value) is not None:
            numeric_hits += 1
    if numeric_hits / len(valid_values) >= 0.95:
        return "numeric"
    name = str(field_name or "").lower()
    if any(token in name for token in ORDINAL_NAME_TOKENS):
        return "ordinal"
    str_vals = [str(v) for v in valid_values]
    if any(ORDINAL_VALUE_RE.match(s.strip()) for s in str_vals):
        return "ordinal"
    if unique_count <= 20:
        return "nominal"
    return "text"
