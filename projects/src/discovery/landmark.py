"""Patient-level landmark mask for Field Bank extraction.

Timed families reuse time_stats slot numbering. The only clock used for
extraction is t_record: keep a slot iff status is not unlocated/non_informative
and finite t_hi <= T. T is an external landmark start time in days, not the
survival endpoint. t_write / updated_datetime is never checked.

Untimed entities (case / demographic / exposures / family_histories) are
not masked. Missing T or missing t_record drops that timed slot.
The Field Bank schema stays shared: dropped values become the existing
missing placeholder, they do not remove columns.
"""

from __future__ import annotations

import argparse

from common.fields import extract_path_values
from common.paths import (
    landmark_tag as build_landmark_tag,
    parse_landmark_time_value,
    resolve_landmark_time_tokens,
)
from time_stats import FAMILY_PATHS, extract_patient_time_record


_FAMILY_PREFIXES = tuple(
    sorted(FAMILY_PATHS.items(), key=lambda item: len(item[1]), reverse=True)
)


def timed_family_for_field(field_path: str) -> tuple[str | None, str]:
    raw = str(field_path or "")
    for family, prefix in _FAMILY_PREFIXES:
        if raw == prefix:
            return family, ""
        if raw.startswith(prefix + "."):
            return family, raw[len(prefix):].lstrip(".")
    return None, raw


def coerce_landmark_time(landmark_time):
    parsed = parse_landmark_time_value(landmark_time)
    if parsed is None:
        raise ValueError("开启 landmark 时必须传入 --landmark_time 天数，不能是 none")
    return float(parsed)


def parse_landmark_options(args) -> tuple[bool, float | None]:
    parsed = parse_landmark_time_value(getattr(args, "landmark_time", None))
    if parsed is None:
        return False, None
    return True, float(parsed)


def add_landmark_cli_args(parser, *, extraction: bool = True) -> None:
    parser.add_argument(
        "--landmark_time",
        required=True,
        help=(
            "全局 landmark 起点：天数、none、逗号列表或 all。none 关闭 Field Bank 取值时的患者级 landmark mask"
            if extraction
            else "全局 landmark 起点：天数、none、逗号列表或 all。筛选产物按 landmark_{T} / landmark_none 分目录；none 时 R0 整层删除路径含 diagnoses / follow_ups 的字段"
        ),
    )


def with_landmark_time(args, landmark_time):
    bound = argparse.Namespace(**vars(args))
    bound.landmark_time = landmark_time
    bound.landmark_tag = landmark_dir_tag(bound)
    return bound


def iter_landmark_args(args, *, scan_roots=None, context: str | None = None):
    tokens = resolve_landmark_time_tokens(
        getattr(args, "landmark_time", None),
        scan_roots=scan_roots,
        context=context,
    )
    for token in tokens:
        yield with_landmark_time(args, token)


def landmark_dir_tag(args) -> str:
    use_landmark, landmark_time = parse_landmark_options(args)
    return build_landmark_tag(no_landmark=not use_landmark, landmark_time=landmark_time)


def landmark_policy(use_landmark: bool) -> str:
    return "t_hi_le_landmark_time" if use_landmark else "off"


def patient_landmark(
    case: dict,
    landmark_time,
    dataset_name: str | None = None,
) -> dict:
    record = extract_patient_time_record(case, dataset_name=dataset_name)
    return {
        "last_time": coerce_landmark_time(landmark_time),
        "slots": record.get("_slots") or {},
        "record": record,
    }


def resolve_landmark(
    case: dict,
    landmark=True,
    dataset_name: str | None = None,
    landmark_time=None,
):
    if landmark is False or landmark is None:
        return None
    if landmark is True:
        return patient_landmark(case, landmark_time, dataset_name=dataset_name)
    return landmark


def slot_passes_landmark(slot: dict, landmark: dict) -> bool:
    last_time = landmark.get("last_time")
    if last_time is None:
        return False
    status = slot.get("record_status")
    if status in {"unlocated", "non_informative"}:
        return False
    days = slot.get("record_hi")
    if days is None:
        days = slot.get("record_days")
    if days is None or days == float("inf"):
        return False
    return days <= last_time


def passing_family_objects(field_path: str, landmark: dict) -> tuple[str | None, str, list]:
    family, remainder = timed_family_for_field(field_path)
    if family is None:
        return None, remainder, []
    objs = []
    for slot in landmark.get("slots", {}).get(family) or []:
        if slot_passes_landmark(slot, landmark) and isinstance(slot.get("obj"), dict):
            objs.append(slot["obj"])
    return family, remainder, objs


def extract_from_objects(objects: list, remainder: str) -> list:
    if not remainder:
        return list(objects)
    values = []
    for obj in objects:
        if isinstance(obj, dict):
            values.extend(extract_path_values(obj, remainder))
    return values
