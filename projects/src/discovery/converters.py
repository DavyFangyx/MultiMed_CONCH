"""Field Bank value converters.

清单（convert 列填这些名字）：
- days_to_years
- int

空 convert 表示不换算。
"""

from __future__ import annotations

import re

from common.types import to_numeric


def _clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return text


def parse_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _clean_text(value)
    if not text:
        return None
    number = to_numeric(text)
    if number is not None:
        return float(number)
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def days_to_years(value) -> str:
    """天数转年：>365 则 int(x / 365.25)，否则视为已经是年。"""
    number = parse_number(value)
    if number is None:
        return _clean_text(value) or str(value)
    years = int(number / 365.25) if number > 365 else int(number)
    return str(years)


def int_(value) -> str:
    """去掉小数部分，167.0 -> 167。"""
    number = parse_number(value)
    if number is None:
        return _clean_text(value) or str(value)
    return str(int(number))


CONVERTERS = {
    "days_to_years": days_to_years,
    "int": int_,
}


def convert_value(value, convert: str | None) -> str:
    name = _clean_text(convert).lower()
    if not name:
        return str(value)
    func = CONVERTERS.get(name)
    if func is None:
        known = ", ".join(sorted(CONVERTERS))
        raise ValueError(f"未知 convert: {convert!r}。允许值为空或 {known}")
    return func(value)


def known_converters() -> set[str]:
    return set(CONVERTERS) | {""}
