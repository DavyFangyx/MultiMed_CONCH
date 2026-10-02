"""Test_1b landmark support for the A_manual pipeline.

The mask is the *same* patient-level time model the Field Bank / leak audit use
(`projects/src/discovery/landmark.py` + `projects/src/time_stats.py`, wired in
here through sys.path). It acts only on timed families: a timed entity is
dropped iff it has a slot of its own and that slot fails the mask
(`record_status` in {unlocated, non_informative}, or no finite `t_hi <= T`).

Untimed families (demographic / exposures / project) and entities the time
model never turns into a slot (follow_up containers, case-level treatments,
negative-therapy records) pass through untouched - exactly as in the Field
Bank, where those entities are not part of the timed value universe.

Missing handling is shared by both arms: a dropped value falls back to the
existing A_pipeline placeholder ("not reported" / "unknown" / "Stage X" ...)
because A_pipeline's own extract logic runs unchanged on the masked case.
"""

from __future__ import annotations

import sys
from pathlib import Path


A_PIPELINE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = A_PIPELINE_ROOT.parent
PROJECTS_SRC = PROJECT_ROOT / "src"

LANDMARK_NONE_TAG = "landmark_none"

TIMED_FAMILIES = (
    "diagnoses",
    "diagnoses_treatments",
    "diagnoses_pathology_details",
    "follow_ups",
    "follow_ups_molecular_tests",
    "follow_ups_other_clinical_attributes",
)

_OFF_TOKENS = frozenset({"none", "off", "false"})


def _ensure_projects_src_on_path() -> None:
    """Put projects/src on sys.path so discovery.landmark / time_stats import."""
    for path in (PROJECTS_SRC, PROJECT_ROOT):
        text = str(path)
        if text not in sys.path:
            sys.path.append(text)


_ensure_projects_src_on_path()

from common.paths import landmark_tag as _projects_landmark_tag  # noqa: E402
from discovery.landmark import patient_landmark, slot_passes_landmark  # noqa: E402


class LandmarkSetting:
    """Parsed `--landmark_time` for one command invocation.

    `provided` is False when the flag was not passed at all: every command then
    keeps the legacy behaviour (legacy output dirs, legacy cindex table).
    `use_landmark` is True only for a numeric day count; `none` is the explicit
    landmark_none arm.
    """

    __slots__ = ("raw", "provided", "use_landmark", "landmark_time")

    def __init__(self, raw=None, provided=False, use_landmark=False, landmark_time=None):
        self.raw = raw
        self.provided = provided
        self.use_landmark = use_landmark
        self.landmark_time = landmark_time

    @property
    def encode_subdir(self) -> str:
        """Outputs subdir: "" when landmark is off, else landmark_{T}."""
        if not self.use_landmark:
            return ""
        return landmark_tag(landmark_time=self.landmark_time)

    @property
    def arm_tag(self) -> str:
        """cindex marker/run_name suffix: "" legacy, else landmark_none/_0/_365."""
        if not self.provided:
            return ""
        if not self.use_landmark:
            return LANDMARK_NONE_TAG
        return landmark_tag(landmark_time=self.landmark_time)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"LandmarkSetting(provided={self.provided}, use_landmark={self.use_landmark}, "
            f"landmark_time={self.landmark_time})"
        )


def parse_landmark_setting(raw) -> LandmarkSetting:
    """Parse the raw CLI token. None/"" = flag absent (legacy behaviour)."""
    if raw is None or raw is False:
        return LandmarkSetting(raw=raw, provided=False)
    if isinstance(raw, str) and not raw.strip():
        return LandmarkSetting(raw=raw, provided=False)
    if raw is True:
        raise ValueError("--landmark_time 需要天数（0/365/730）或 none")

    token = str(raw).strip().lower()
    if token in _OFF_TOKENS:
        return LandmarkSetting(raw=raw, provided=True)
    try:
        value = float(token)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"--landmark_time 必须是非负整数天或 none，当前是 {raw!r}"
        ) from exc
    if value < 0 or not value.is_integer():
        raise ValueError(f"--landmark_time 必须是非负整数天或 none，当前是 {raw!r}")
    return LandmarkSetting(raw=raw, provided=True, use_landmark=True, landmark_time=int(value))


def landmark_tag(*, no_landmark: bool = False, landmark_time=None) -> str:
    """landmark_none / landmark_{T}. Same spelling as projects/src."""
    return _projects_landmark_tag(no_landmark=no_landmark, landmark_time=landmark_time)


def landmark_dir(base, subdir: str) -> Path:
    """Append the landmark subdir when there is one ("" keeps the legacy dir)."""
    path = Path(base)
    return path / subdir if subdir else path


def _slot_index(slots: dict, family: str, landmark: dict) -> tuple[set, set]:
    """(ids with a slot, ids whose slot passes) for one timed family."""
    slotted, passing = set(), set()
    for slot in slots.get(family) or []:
        if not isinstance(slot, dict):
            continue
        obj = slot.get("obj")
        if not isinstance(obj, dict):
            continue
        slotted.add(id(obj))
        if slot_passes_landmark(slot, landmark):
            passing.add(id(obj))
    return slotted, passing


def _keeps(obj, index: tuple[set, set]) -> bool:
    slotted, passing = index
    return id(obj) not in slotted or id(obj) in passing


def _filter_children(parent: dict, key: str, index: tuple[set, set]) -> dict:
    items = parent.get(key)
    if not isinstance(items, list):
        return parent
    kept = [
        item for item in items if not isinstance(item, dict) or _keeps(item, index)
    ]
    if len(kept) == len(items):
        return parent
    masked = dict(parent)
    masked[key] = kept
    return masked


def _mask_diagnosis(diagnosis, index: dict):
    if not isinstance(diagnosis, dict):
        return diagnosis
    if not _keeps(diagnosis, index["diagnoses"]):
        return None
    masked = _filter_children(diagnosis, "treatments", index["diagnoses_treatments"])
    masked = _filter_children(masked, "pathology_details", index["diagnoses_pathology_details"])
    return masked


def _mask_follow_up(follow_up, index: dict):
    if not isinstance(follow_up, dict):
        return follow_up
    if not _keeps(follow_up, index["follow_ups"]):
        return None
    masked = _filter_children(
        follow_up, "other_clinical_attributes", index["follow_ups_other_clinical_attributes"]
    )
    masked = _filter_children(masked, "molecular_tests", index["follow_ups_molecular_tests"])
    return masked


def mask_case(case: dict, landmark_time, dataset_name: str | None = None) -> dict:
    """Copy of `case` with timed slots whose `t_hi > T` dropped.

    landmark_time None keeps the legacy behaviour and returns `case` itself.
    """
    if not isinstance(case, dict) or landmark_time is None:
        return case

    landmark = patient_landmark(case, landmark_time, dataset_name=dataset_name)
    slots = landmark.get("slots") or {}
    index = {family: _slot_index(slots, family, landmark) for family in TIMED_FAMILIES}

    masked = dict(case)
    diagnoses = case.get("diagnoses")
    if isinstance(diagnoses, list):
        masked["diagnoses"] = [
            item
            for item in (_mask_diagnosis(diagnosis, index) for diagnosis in diagnoses)
            if item is not None
        ]
    follow_ups = case.get("follow_ups")
    if isinstance(follow_ups, list):
        masked["follow_ups"] = [
            item
            for item in (_mask_follow_up(follow_up, index) for follow_up in follow_ups)
            if item is not None
        ]
    return masked
