"""Shared type inference for clinical fields."""

from __future__ import annotations

import re


ROMAN_NUMERALS = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "VII": 7,
    "VIII": 8,
    "IX": 9,
    "X": 10,
}

# T2, N1mi, G3, pT2a
_STAGE_TOKEN_RE = re.compile(r"^(?P<prefix>[A-Za-z]{1,6})(?P<num>\d+)(?P<suffix>[A-Za-z]*)$")
# Stage IIA / Stage 2
_STAGE_WORDS_RE = re.compile(
    r"^(?P<prefix>stage\s+)(?P<num>VIII|VII|III|II|IV|IX|VI|V|X|I|\d+)(?P<suffix>[A-Za-z]*)$",
    re.IGNORECASE,
)


def to_numeric(value):
    try:
        if isinstance(value, bool):
            return float(int(value))
        return float(value)
    except Exception:
        return None


def _flatten_vocab(valid_values: list) -> list[str]:
    tokens = []
    for value in valid_values:
        text = str(value).strip()
        if not text:
            continue
        if " | " in text:
            tokens.extend(part.strip() for part in text.split(" | ") if part.strip())
        else:
            tokens.append(text)
    return tokens


def _parse_stage_token(value: str) -> tuple[str, int] | None:
    text = str(value).strip()
    if not text or "." in text or "/" in text:
        return None

    match = _STAGE_WORDS_RE.match(text)
    if match:
        prefix = re.sub(r"\s+", " ", match.group("prefix")).strip().lower()
        raw_num = match.group("num").upper()
        number = ROMAN_NUMERALS[raw_num] if raw_num in ROMAN_NUMERALS else int(raw_num)
        return prefix, number

    match = _STAGE_TOKEN_RE.match(text)
    if match:
        return match.group("prefix").upper(), int(match.group("num"))
    return None


def is_ordinal_stage(valid_values: list) -> bool:
    vocab = sorted(set(_flatten_vocab(valid_values)))
    if len(vocab) < 2:
        return False

    parsed = [item for item in (_parse_stage_token(token) for token in vocab) if item]
    if len(parsed) < 2:
        return False
    if len(parsed) < 0.5 * len(vocab):
        return False

    prefixes = {prefix for prefix, _ in parsed}
    numbers = {number for _, number in parsed}
    return len(prefixes) == 1 and len(numbers) >= 2


def infer_type(field_name: str, valid_values: list, unique_count: int) -> str:
    if not valid_values:
        return "empty"

    numeric_hits = 0
    for value in valid_values:
        if to_numeric(value) is not None:
            numeric_hits += 1
    if numeric_hits / len(valid_values) >= 0.95:
        return "numeric"

    if is_ordinal_stage(valid_values):
        return "ordinal_stage"
    if unique_count <= 20:
        return "ordinal_class"
    return "text"
