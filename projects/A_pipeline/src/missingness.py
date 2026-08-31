"""Shared missingness vocabulary and three-state classification."""

from __future__ import annotations


SENTINEL_VALUES = {
    "not reported",
    "unknown",
    "not applicable",
    "not available",
    "not evaluated",
    "not otherwise specified",
    "indeterminate",
    "cannot be assessed",
    "unspecified",
    "na",
    "n/a",
    "none",
    "null",
    "missing",
    "--",
}

SCHEME_FALLBACK_SENTINELS = {
    "",
    "not reported",
    "unknown",
    "not applicable",
    "--",
}


def normalize_text(value) -> str:
    return str(value).strip().lower()


def is_missing_token(value, extra: set[str] | None = None) -> bool:
    cleaned = " ".join(normalize_text(value).split())
    if extra and cleaned in extra:
        return True
    return cleaned in SENTINEL_VALUES or cleaned == ""


def classify_raw_value(value) -> str:
    """Return one of: null, sentinel, valid."""
    if value is None:
        return "null"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "null"
        if normalize_text(text) in SENTINEL_VALUES:
            return "sentinel"
        return "valid"
    if isinstance(value, list):
        return "null" if len(value) == 0 else "valid"
    if isinstance(value, dict):
        return "null" if len(value) == 0 else "valid"
    return "valid"


def is_non_empty_value(value) -> bool:
    return classify_raw_value(value) == "valid"


def clean_value(value, fallback="not reported") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if text.lower() in SCHEME_FALLBACK_SENTINELS:
        return fallback
    return text
